"""Physical disk management tools for Proxmox VE nodes.

Provides tools for listing, partitioning, formatting, mounting, and
unmounting physical block devices. Uses the Proxmox API where available
and SSH for operations the API does not cover.
"""

import json
import logging
from typing import TYPE_CHECKING

from proxmox_mcp.utils.errors import (
    DeviceInUseError,
    DeviceNotFoundError,
    SafetyGateError,
    format_error_response,
)
from proxmox_mcp.utils.formatters import format_bytes
from proxmox_mcp.utils.sanitizers import (
    check_shell_injection,
    validate_device_path,
    validate_filesystem,
    validate_label,
    validate_mkfs_options,
    validate_mount_options,
    validate_mount_path,
    validate_partition_table,
    validate_uuid,
)
from proxmox_mcp.utils.validators import validate_node_name

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from proxmox_mcp.client import ProxmoxClient
    from proxmox_mcp.ssh import SSHExecutor

logger = logging.getLogger("proxmox-mcp")


def get_client() -> "ProxmoxClient":
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp() -> "FastMCP":
    from proxmox_mcp.server import mcp

    return mcp


def get_ssh() -> "SSHExecutor":
    from proxmox_mcp.server import ssh_executor

    return ssh_executor


mcp = get_mcp()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _check_device_exists(ssh, node: str, device: str) -> None:
    """Verify a device exists and is a block device."""
    result = await ssh.execute(node, f"test -b {device} && echo exists")
    if result.exit_code != 0 or "exists" not in result.stdout:
        raise DeviceNotFoundError(f"Device {device} not found or is not a block device on {node}.")


async def _check_not_boot_disk(ssh, node: str, device: str) -> None:
    """Reject if any partition on the device is mounted as /, /boot, or /boot/efi."""
    result = await ssh.execute(node, f"lsblk -no MOUNTPOINT {device} {device}[0-9]* 2>/dev/null")
    if result.success:
        mounts = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        critical = {"/", "/boot", "/boot/efi"}
        found = critical.intersection(mounts)
        if found:
            raise SafetyGateError(
                f"Device {device} contains boot partitions mounted at: {', '.join(found)}. "
                f"Refusing to operate on a boot disk."
            )


async def _check_not_in_use(ssh, node: str, device: str) -> dict | None:
    """Check if any partition on the device is mounted, in LVM, ZFS, or MD RAID.

    Returns details about usage if in use, None if free.
    Raises DeviceInUseError if the device is in use.
    """
    # Check mounts
    result = await ssh.execute(
        node,
        f"findmnt -rno SOURCE,TARGET -S {device} 2>/dev/null; "
        f"findmnt -rno SOURCE,TARGET -S {device}[0-9]* 2>/dev/null",
    )
    if result.success and result.stdout.strip():
        raise DeviceInUseError(f"Device {device} has mounted partitions:\n{result.stdout.strip()}")

    # Check LVM
    result = await ssh.execute(
        node, f"pvs --noheadings -o pv_name,vg_name 2>/dev/null | grep -E '{device}'"
    )
    if result.success and result.stdout.strip():
        raise DeviceInUseError(
            f"Device {device} is an LVM physical volume:\n{result.stdout.strip()}"
        )

    # Check ZFS
    result = await ssh.execute(
        node, "zpool status 2>/dev/null | grep -E '" + device.split("/")[-1] + "'"
    )
    if result.success and result.stdout.strip():
        raise DeviceInUseError(f"Device {device} is part of a ZFS pool:\n{result.stdout.strip()}")

    # Check MD RAID
    result = await ssh.execute(node, f"grep '{device.split('/')[-1]}' /proc/mdstat 2>/dev/null")
    if result.success and result.stdout.strip():
        raise DeviceInUseError(
            f"Device {device} is part of an MD RAID array:\n{result.stdout.strip()}"
        )

    return None


# ---------------------------------------------------------------------------
# Tool 1: list_physical_disks
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_physical_disks(
    node: str,
    include_partitions: bool = True,
    filter_unused: bool = False,
) -> dict:
    """Enumerate all physical block devices on a Proxmox node.

    Returns disk model, serial, size, SMART health, partition details,
    and usage status (mounted, LVM, ZFS, etc.).

    Args:
        node: Target Proxmox node name (e.g., 'hobbiton').
        include_partitions: Include partition table details for each disk.
        filter_unused: Only show disks not currently in use.
    """
    try:
        client = get_client()
        ssh = get_ssh()
        validate_node_name(node)
        client.validate_node(node)
        logger.info("Listing physical disks on node '%s'", node)

        # Primary: Proxmox API for disk list
        api_disks = await client.api_call(client.api.nodes(node).disks.list.get)

        # Enrich with SSH lsblk for partition-level detail
        lsblk_data = {}
        if include_partitions:
            result = await ssh.execute(
                node,
                "lsblk -Jb -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID,MODEL,SERIAL,"
                "ROTA,TRAN,PTTYPE,PKNAME",
            )
            if result.success:
                try:
                    parsed = json.loads(result.stdout)
                    for dev in parsed.get("blockdevices", []):
                        lsblk_data[f"/dev/{dev['name']}"] = dev
                except (json.JSONDecodeError, KeyError):
                    logger.warning("Failed to parse lsblk JSON output")

        # Check LVM PVs for usage detection
        lvm_pvs = set()
        pv_result = await ssh.execute(node, "pvs --noheadings -o pv_name 2>/dev/null")
        if pv_result.success:
            lvm_pvs = {line.strip() for line in pv_result.stdout.splitlines() if line.strip()}

        disks = []
        for api_disk in api_disks:
            dev_path = api_disk.get("devpath", "")
            size_bytes = api_disk.get("size", 0)

            # Determine usage type
            used = api_disk.get("used", "")
            usage_type = used if used else "unused"
            in_use = usage_type != "unused"

            if filter_unused and in_use:
                continue

            disk_info = {
                "device": dev_path,
                "model": api_disk.get("model", "Unknown"),
                "serial": api_disk.get("serial", "Unknown"),
                "size_bytes": size_bytes,
                "size_human": format_bytes(size_bytes),
                "transport": api_disk.get("type", "unknown"),
                "rotation": bool(api_disk.get("rpm", 0)),
                "smart_status": api_disk.get("health", "UNKNOWN"),
                "gpt_label": api_disk.get("gpt", "unknown"),
                "in_use": in_use,
                "usage_type": usage_type,
            }

            # Add partition info from lsblk
            if include_partitions and dev_path in lsblk_data:
                lsblk_dev = lsblk_data[dev_path]
                partitions = []
                for child in lsblk_dev.get("children", []):
                    if child.get("type") not in ("part", "partition"):
                        continue
                    child_dev = f"/dev/{child['name']}"
                    part_in_use = bool(child.get("mountpoint")) or child_dev in lvm_pvs
                    partitions.append(
                        {
                            "device": child_dev,
                            "size_bytes": child.get("size", 0),
                            "size_human": format_bytes(child.get("size", 0)),
                            "filesystem": child.get("fstype") or "none",
                            "mountpoint": child.get("mountpoint"),
                            "uuid": child.get("uuid"),
                            "in_use": part_in_use,
                        }
                    )
                disk_info["partitions"] = partitions

            disks.append(disk_info)

        return {
            "status": "success",
            "node": node,
            "count": len(disks),
            "disks": disks,
        }
    except Exception as e:
        logger.error("Failed to list physical disks on '%s': %s", node, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Tool 2: partition_disk
# ---------------------------------------------------------------------------


@mcp.tool()
async def partition_disk(
    node: str,
    device: str,
    partition_table: str = "gpt",
    filesystem: str = "ext4",
    label: str | None = None,
    confirm_destructive: bool = False,
) -> dict:
    """Create a partition table and single partition on a physical disk.

    Creates a GPT (or msdos) partition table with a single partition spanning
    the entire disk, optionally formatted with a filesystem.

    WARNING: This DESTROYS all data on the target device.

    Args:
        node: Target Proxmox node name.
        device: Whole disk device path (e.g., '/dev/sdb'). Must NOT be a partition.
        partition_table: Partition table type: 'gpt' or 'msdos'.
        filesystem: Filesystem to create: 'ext4', 'xfs', or 'vfat'. Use 'none' to skip.
        label: Optional filesystem label (max 16 chars, alphanumeric).
        confirm_destructive: MUST be True. Acknowledges data destruction.
    """
    try:
        ssh = get_ssh()
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)

        # Validate all inputs
        validate_device_path(device, allow_partition=False)
        validate_partition_table(partition_table)
        if filesystem != "none":
            validate_filesystem(filesystem)
        if label:
            validate_label(label)

        # Safety gate 1: confirm_destructive
        if not confirm_destructive:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will DESTROY ALL DATA on {device}. "
                    f"A new {partition_table} partition table will be created "
                    f"with a single {filesystem} partition."
                ),
                "action": "Call partition_disk again with confirm_destructive=True to proceed.",
                "device": device,
            }

        # Safety gate 2: device exists
        await _check_device_exists(ssh, node, device)

        # Safety gate 3: not a boot disk
        await _check_not_boot_disk(ssh, node, device)

        # Safety gate 4: not in active use
        await _check_not_in_use(ssh, node, device)

        # Dry run check
        if client.is_dry_run:
            return client.dry_run_response(
                "partition_disk",
                device=device,
                node=node,
                partition_table=partition_table,
                filesystem=filesystem,
            )

        logger.warning(
            "Partitioning disk %s on %s (table=%s, fs=%s)",
            device,
            node,
            partition_table,
            filesystem,
        )

        # Step 1: Wipe existing signatures
        result = await ssh.execute(node, f"wipefs -a {device}", timeout=30)
        if not result.success:
            return format_error_response(
                Exception(f"wipefs failed: {result.stderr}"),
                suggestion="Check that the device is not in use.",
            )

        # Step 2: Create GPT partition table and single partition spanning entire disk
        # Use sgdisk (available on Proxmox) with parted as fallback
        # sgdisk -Z: zap all partition data, -n 1:0:0: new partition 1 using all space,
        # -t 1:8300: set type to Linux filesystem
        if partition_table == "gpt":
            result = await ssh.execute(
                node, f"sgdisk -Z {device} && sgdisk -n 1:0:0 -t 1:8300 {device}", timeout=30
            )
        else:
            # msdos/MBR: fall back to sfdisk
            result = await ssh.execute(
                node, f"echo ',,L;' | sfdisk --label dos {device}", timeout=30
            )
        if not result.success:
            return format_error_response(
                Exception(f"Partitioning failed: {result.stderr}")
            )

        # Step 3: Re-read partition table
        await ssh.execute(node, f"blockdev --rereadpt {device} && sleep 1", timeout=15)

        partition = f"{device}1"

        # Step 5: Create filesystem (if requested)
        fs_uuid = None
        if filesystem != "none":
            label_flag = ""
            if label:
                if filesystem == "vfat":
                    label_flag = f" -n {label}"
                else:
                    label_flag = f" -L {label}"

            mkfs_cmd = f"mkfs.{filesystem}{label_flag} {partition}"
            result = await ssh.execute(node, mkfs_cmd, timeout=120)
            if not result.success:
                # Partial success: partition created but filesystem failed
                return {
                    "status": "partial_success",
                    "warning": "Partition created but filesystem creation failed.",
                    "device": device,
                    "partition": partition,
                    "partition_table": partition_table,
                    "filesystem_error": result.stderr,
                }

        # Step 6: Get UUID
        blkid_result = await ssh.execute(node, f"blkid -o export {partition}")
        if blkid_result.success:
            for line in blkid_result.stdout.splitlines():
                if line.startswith("UUID="):
                    fs_uuid = line.split("=", 1)[1]
                    break

        return {
            "status": "success",
            "device": device,
            "partition_table": partition_table,
            "partitions_created": [
                {
                    "device": partition,
                    "filesystem": filesystem if filesystem != "none" else None,
                    "uuid": fs_uuid,
                    "label": label,
                    "size_human": "entire disk",
                }
            ],
        }
    except Exception as e:
        logger.error("Failed to partition disk %s on '%s': %s", device, node, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Tool 3: format_disk
# ---------------------------------------------------------------------------


@mcp.tool()
async def format_disk(
    node: str,
    device: str,
    filesystem: str,
    label: str | None = None,
    options: str | None = None,
    confirm_destructive: bool = False,
) -> dict:
    """Create a filesystem on an existing partition or disk.

    Useful when a partition already exists but needs a new or different filesystem.

    WARNING: This DESTROYS all data on the target device/partition.

    Args:
        node: Target Proxmox node name.
        device: Partition or disk path (e.g., '/dev/sdb1').
        filesystem: Filesystem type: 'ext4', 'xfs', or 'vfat'.
        label: Optional filesystem label (max 16 chars).
        options: Additional mkfs options (e.g., '-m 1'). Validated against allowlist.
        confirm_destructive: MUST be True. Acknowledges data destruction.
    """
    try:
        ssh = get_ssh()
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)

        # Validate inputs
        validate_device_path(device, allow_partition=True)
        validate_filesystem(filesystem)
        if label:
            validate_label(label)
        if options:
            validate_mkfs_options(options)

        # Safety gate: confirm
        if not confirm_destructive:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will DESTROY ALL DATA on {device}. "
                    f"A new {filesystem} filesystem will be created."
                ),
                "action": "Call format_disk again with confirm_destructive=True to proceed.",
                "device": device,
            }

        # Safety gate: device exists
        await _check_device_exists(ssh, node, device)

        # Safety gate: not mounted
        mount_check = await ssh.execute(node, f"findmnt -rno TARGET {device} 2>/dev/null")
        if mount_check.success and mount_check.stdout.strip():
            raise DeviceInUseError(
                f"Device {device} is mounted at {mount_check.stdout.strip()}. Unmount first."
            )

        if client.is_dry_run:
            return client.dry_run_response(
                "format_disk",
                device=device,
                node=node,
                filesystem=filesystem,
            )

        logger.warning("Formatting %s on %s as %s", device, node, filesystem)

        # Wipe existing signatures
        await ssh.execute(node, f"wipefs -a {device}", timeout=30)

        # Build mkfs command
        label_flag = ""
        if label:
            label_flag = f" -n {label}" if filesystem == "vfat" else f" -L {label}"

        extra = f" {options}" if options else ""
        force = " -F" if filesystem == "ext4" else (" -f" if filesystem == "xfs" else "")
        mkfs_cmd = f"mkfs.{filesystem}{force}{label_flag}{extra} {device}"

        result = await ssh.execute(node, mkfs_cmd, timeout=120)
        if not result.success:
            return format_error_response(Exception(f"mkfs.{filesystem} failed: {result.stderr}"))

        # Get UUID
        fs_uuid = None
        blkid_result = await ssh.execute(node, f"blkid -o export {device}")
        if blkid_result.success:
            for line in blkid_result.stdout.splitlines():
                if line.startswith("UUID="):
                    fs_uuid = line.split("=", 1)[1]
                    break

        return {
            "status": "success",
            "device": device,
            "filesystem": filesystem,
            "uuid": fs_uuid,
            "label": label,
        }
    except Exception as e:
        logger.error("Failed to format %s on '%s': %s", device, node, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Tool 4: create_mount_point
# ---------------------------------------------------------------------------


@mcp.tool()
async def create_mount_point(
    node: str,
    device: str,
    mount_path: str,
    filesystem: str | None = None,
    mount_options: str = "defaults",
    persist_fstab: bool = True,
) -> dict:
    """Mount a filesystem to a path and optionally persist in /etc/fstab.

    Args:
        node: Target Proxmox node name.
        device: Device or partition path (e.g., '/dev/sdb1').
        mount_path: Absolute path for the mount point. Must be under /mnt/, /srv/, or /media/.
        filesystem: Filesystem type. Auto-detected if omitted.
        mount_options: Mount options (e.g., 'defaults,noatime'). Validated against allowlist.
        persist_fstab: Add entry to /etc/fstab for persistence across reboots.
    """
    try:
        ssh = get_ssh()
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)

        # Validate inputs
        validate_device_path(device, allow_partition=True)
        validate_mount_path(mount_path)
        validate_mount_options(mount_options)
        if filesystem:
            validate_filesystem(filesystem)

        # Safety gate: device exists and has a filesystem
        await _check_device_exists(ssh, node, device)

        blkid_result = await ssh.execute(node, f"blkid -o export {device}")
        detected_fs = None
        device_uuid = None
        if blkid_result.success:
            for line in blkid_result.stdout.splitlines():
                if line.startswith("TYPE="):
                    detected_fs = line.split("=", 1)[1]
                elif line.startswith("UUID="):
                    device_uuid = line.split("=", 1)[1]

        fs_type = filesystem or detected_fs
        if not fs_type:
            return format_error_response(
                Exception(f"No filesystem detected on {device}. Format it first."),
                suggestion="Use format_disk to create a filesystem before mounting.",
            )

        # Safety gate: path not already a mount point
        mount_check = await ssh.execute(node, f"findmnt -rno TARGET {mount_path} 2>/dev/null")
        if mount_check.success and mount_check.stdout.strip():
            raise DeviceInUseError(f"Path {mount_path} is already a mount point.")

        if client.is_dry_run:
            return client.dry_run_response(
                "create_mount_point",
                device=device,
                mount_path=mount_path,
                node=node,
                filesystem=fs_type,
            )

        logger.warning(
            "Mounting %s at %s on %s (fs=%s, options=%s)",
            device,
            mount_path,
            node,
            fs_type,
            mount_options,
        )

        # Create mount directory
        result = await ssh.execute(node, f"mkdir -p {mount_path}")
        if not result.success:
            return format_error_response(
                Exception(f"Failed to create mount directory: {result.stderr}")
            )

        # Mount
        result = await ssh.execute(
            node, f"mount -t {fs_type} -o {mount_options} {device} {mount_path}"
        )
        if not result.success:
            return format_error_response(Exception(f"Mount failed: {result.stderr}"))

        # Verify mount
        verify = await ssh.execute(node, f"findmnt -rno SOURCE {mount_path}")
        if not verify.success or not verify.stdout.strip():
            return format_error_response(
                Exception("Mount appeared to succeed but verification failed.")
            )

        # Persist to fstab
        fstab_added = False
        fstab_line = None
        if persist_fstab and device_uuid:
            # Validate UUID format before shell interpolation
            validate_uuid(device_uuid)
            fstab_line = f"UUID={device_uuid} {mount_path} {fs_type} {mount_options} 0 2"

            # Backup fstab
            await ssh.execute(node, "cp /etc/fstab /etc/fstab.bak.$(date +%s)")

            # Add entry using printf for safety
            result = await ssh.execute(
                node, f"printf '%s\\n' '{fstab_line}' >> /etc/fstab"
            )
            if result.success:
                # Validate fstab
                validate = await ssh.execute(node, "mount -a --fake")
                if validate.success:
                    fstab_added = True
                else:
                    # Rollback fstab
                    logger.error("fstab validation failed, rolling back: %s", validate.stderr)
                    await ssh.execute(
                        node,
                        "cp $(ls -t /etc/fstab.bak.* | head -1) /etc/fstab",
                    )
                    logger.warning("fstab rolled back after validation failure")

        return {
            "status": "success",
            "device": device,
            "uuid": device_uuid,
            "mount_path": mount_path,
            "filesystem": fs_type,
            "mount_options": mount_options,
            "fstab_entry_added": fstab_added,
            "fstab_line": fstab_line if fstab_added else None,
        }
    except Exception as e:
        logger.error("Failed to mount %s at %s on '%s': %s", device, mount_path, node, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Tool 5: unmount_path
# ---------------------------------------------------------------------------


@mcp.tool()
async def unmount_path(
    node: str,
    mount_path: str,
    remove_fstab_entry: bool = False,
    force: bool = False,
) -> dict:
    """Unmount a filesystem and optionally remove its fstab entry.

    Args:
        node: Target Proxmox node name.
        mount_path: Path to unmount (e.g., '/mnt/data').
        remove_fstab_entry: Remove the matching fstab entry.
        force: Use lazy unmount (umount -l) if device is busy.
    """
    try:
        ssh = get_ssh()
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        validate_mount_path(mount_path)

        # Safety gate: reject critical system mounts
        check_shell_injection(mount_path, "mount_path")

        # Verify actually mounted
        check = await ssh.execute(node, f"findmnt -rno SOURCE {mount_path} 2>/dev/null")
        if not check.success or not check.stdout.strip():
            return format_error_response(
                Exception(f"Path {mount_path} is not currently mounted."),
                suggestion="Check the mount path and try again.",
            )

        if client.is_dry_run:
            return client.dry_run_response(
                "unmount_path",
                mount_path=mount_path,
                node=node,
            )

        logger.warning("Unmounting %s on %s (force=%s)", mount_path, node, force)

        # Unmount
        umount_flag = " -l" if force else ""
        result = await ssh.execute(node, f"umount{umount_flag} {mount_path}")
        if not result.success:
            return format_error_response(
                Exception(f"Unmount failed: {result.stderr}"),
                suggestion="Try with force=True for lazy unmount, or check open files with lsof.",
            )

        # Remove fstab entry
        fstab_removed = False
        if remove_fstab_entry:
            # Backup fstab first
            await ssh.execute(node, "cp /etc/fstab /etc/fstab.bak.$(date +%s)")

            # Remove line matching the mount path
            escaped_path = mount_path.replace("/", "\\/")
            result = await ssh.execute(node, f"sed -i '/ {escaped_path} /d' /etc/fstab")
            if result.success:
                # Validate fstab after modification
                validate = await ssh.execute(node, "mount -a --fake")
                if validate.success:
                    fstab_removed = True
                else:
                    logger.error("fstab validation failed after removal, rolling back")
                    await ssh.execute(
                        node,
                        "cp $(ls -t /etc/fstab.bak.* | head -1) /etc/fstab",
                    )

        return {
            "status": "success",
            "mount_path": mount_path,
            "unmounted": True,
            "fstab_entry_removed": fstab_removed,
        }
    except Exception as e:
        logger.error("Failed to unmount %s on '%s': %s", mount_path, node, e)
        return format_error_response(e)
