"""QEMU/KVM VM management tools."""

import json
import logging
from typing import TYPE_CHECKING, Any

from proxmox_mcp.utils.errors import InvalidParameterError, format_error_response
from proxmox_mcp.utils.formatters import format_task_result, format_vm_summary
from proxmox_mcp.utils.validators import validate_node_name, validate_vmid

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from proxmox_mcp.client import ProxmoxClient

logger = logging.getLogger("proxmox-mcp")

DEFAULT_START_TIMEOUT = 60
DEFAULT_SHUTDOWN_TIMEOUT = 120
MAX_EXTRA_CONFIG_VALUE_LEN = 4096
VALID_VM_STATUSES = frozenset({"running", "stopped", "paused", "suspended"})
VALID_RRD_TIMEFRAMES = frozenset({"hour", "day", "week", "month", "year"})

# Allowlist of VM config keys safe to modify via extra_config.
# Keys NOT in this set are rejected to prevent dangerous operations
# (e.g., hookscript for arbitrary code execution, hostpci for PCI passthrough).
VM_SAFE_CONFIG_KEYS = frozenset(
    {
        # CPU & Memory
        "cores",
        "sockets",
        "vcpus",
        "cpu",
        "cpulimit",
        "cpuunits",
        "memory",
        "balloon",
        "shares",
        "numa",
        # Boot & BIOS
        "boot",
        "bootdisk",
        "bios",
        "machine",
        "ostype",
        # Display
        "vga",
        "tablet",
        # Cloud-init
        "ciuser",
        "cipassword",
        "citype",
        "cicustom",
        "ipconfig0",
        "ipconfig1",
        "ipconfig2",
        "ipconfig3",
        "nameserver",
        "searchdomain",
        "sshkeys",
        # Description & Tags
        "description",
        "tags",
        "name",
        "onboot",
        "startup",
        "protection",
        # Agent
        "agent",
        # Hotplug
        "hotplug",
        # Disk
        "ide0",
        "ide1",
        "ide2",
        "ide3",
        "scsi0",
        "scsi1",
        "scsi2",
        "scsi3",
        "virtio0",
        "virtio1",
        "virtio2",
        "virtio3",
        "sata0",
        "sata1",
        "sata2",
        "sata3",
        "sata4",
        "sata5",
        "efidisk0",
        "tpmstate0",
        # Network
        "net0",
        "net1",
        "net2",
        "net3",
        # Misc safe
        "kvm",
        "localtime",
        "freeze",
        "template",
    }
)


def get_client() -> "ProxmoxClient":
    from proxmox_mcp.server import get_server_client

    return get_server_client()


def get_mcp() -> "FastMCP":
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()


@mcp.tool()
async def list_vms(node: str | None = None, status_filter: str | None = None) -> dict:
    """List all QEMU VMs across the cluster or on a specific node.

    Args:
        node: Filter to a specific node. None for all nodes.
        status_filter: Filter by status - 'running', 'stopped', 'paused',
            'suspended', or None for all.
    """
    try:
        client = get_client()
        if status_filter is not None and status_filter not in VALID_VM_STATUSES:
            return format_error_response(
                InvalidParameterError(
                    f"Invalid status_filter '{status_filter}'. "
                    f"Must be one of: {', '.join(sorted(VALID_VM_STATUSES))} (or omit)."
                )
            )
        if node:
            validate_node_name(node)
            client.validate_node(node)
        resources = await client.api_call(client.api.cluster.resources.get, type="vm")
        vms = [r for r in resources if r.get("type") == "qemu"]
        if node:
            vms = [v for v in vms if v.get("node") == node]
        if status_filter:
            vms = [v for v in vms if v.get("status") == status_filter]
        formatted = [format_vm_summary(v) for v in vms]
        return {"status": "success", "vms": formatted, "total": len(formatted)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_vm_status(vmid: int, node: str | None = None) -> dict:
    """Get detailed status of a specific QEMU VM.

    Args:
        vmid: The VM ID (e.g. 100).
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await client.resolve_node(vmid, node)
        data = await client.api_call(client.api.nodes(node).qemu(vmid).status.current.get)
        return {"status": "success", "vmid": vmid, "node": node, "data": data}
    except Exception as e:
        return format_error_response(e, suggestion="Use list_vms to see available VMs.")


@mcp.tool()
async def get_vm_config(vmid: int, node: str | None = None) -> dict:
    """Get full configuration of a QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await client.resolve_node(vmid, node)
        data = await client.api_call(client.api.nodes(node).qemu(vmid).config.get)
        return {"status": "success", "vmid": vmid, "node": node, "config": data}
    except Exception as e:
        return format_error_response(e, suggestion="Use list_vms to see available VMs.")


@mcp.tool()
async def get_vm_rrd_data(vmid: int, node: str | None = None, timeframe: str = "hour") -> dict:
    """Get VM performance metrics (CPU, memory, disk, network) over time.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
        timeframe: Time range - 'hour', 'day', 'week', 'month', or 'year'.
    """
    try:
        client = get_client()
        if timeframe not in VALID_RRD_TIMEFRAMES:
            return format_error_response(
                InvalidParameterError(
                    f"Invalid timeframe '{timeframe}'. "
                    f"Must be one of: {', '.join(sorted(VALID_RRD_TIMEFRAMES))}."
                )
            )
        validate_vmid(vmid)
        node = await client.resolve_node(vmid, node)
        data = await client.api_call(
            client.api.nodes(node).qemu(vmid).rrddata.get, timeframe=timeframe
        )
        return {
            "status": "success",
            "vmid": vmid,
            "node": node,
            "timeframe": timeframe,
            "data": data,
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def start_vm(
    vmid: int, node: str | None = None, timeout: int = DEFAULT_START_TIMEOUT
) -> dict:
    """Start a stopped QEMU VM.

    Args:
        vmid: The VM ID to start.
        node: The node name. Auto-detected if omitted.
        timeout: Timeout in seconds (default 60).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("start_vm", vmid=vmid, node=node)
        logger.info("Starting VM %d on %s", vmid, node)
        upid = await client.api_call(
            client.api.nodes(node).qemu(vmid).status.start.post, timeout=timeout
        )
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def stop_vm(vmid: int, node: str | None = None) -> dict:
    """Hard stop a QEMU VM (like pulling power). Use shutdown_vm for graceful stop.

    Args:
        vmid: The VM ID to stop.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("stop_vm", vmid=vmid, node=node)
        logger.warning("Hard stopping VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.stop.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def shutdown_vm(
    vmid: int, node: str | None = None, timeout: int = DEFAULT_SHUTDOWN_TIMEOUT
) -> dict:
    """Graceful ACPI shutdown of a QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
        timeout: Accepted for compatibility; the PVE API's default soft-off
            timeout applies (the API endpoint takes no timeout parameter).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("shutdown_vm", vmid=vmid, node=node)
        logger.info("Graceful shutdown of VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.shutdown.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def reboot_vm(vmid: int, node: str | None = None) -> dict:
    """Reboot a QEMU VM via ACPI.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("reboot_vm", vmid=vmid, node=node)
        logger.info("Rebooting VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.reboot.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def suspend_vm(vmid: int, node: str | None = None) -> dict:
    """Suspend/pause a running QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("suspend_vm", vmid=vmid, node=node)
        logger.info("Suspending VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.suspend.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def resume_vm(vmid: int, node: str | None = None) -> dict:
    """Resume a suspended QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("resume_vm", vmid=vmid, node=node)
        logger.info("Resuming VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.resume.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def reset_vm(vmid: int, node: str | None = None) -> dict:
    """Hard reset a QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("reset_vm", vmid=vmid, node=node)
        logger.warning("Hard resetting VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.reset.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def clone_vm(
    vmid: int,
    newid: int,
    name: str,
    node: str | None = None,
    full: bool = True,
    target_node: str | None = None,
    target_storage: str | None = None,
) -> dict:
    """Clone a QEMU VM (full or linked clone).

    Args:
        vmid: Source VM ID to clone.
        newid: New VMID for the clone.
        name: Name for the cloned VM.
        node: Source node. Auto-detected if omitted.
        full: True for full clone, False for linked clone (default True).
        target_node: Destination node for the clone (optional).
        target_storage: Storage for the clone's disks (optional).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_vmid(newid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("clone_vm", vmid=vmid, newid=newid, name=name, node=node)
        kwargs: dict[str, Any] = {"newid": newid, "name": name, "full": 1 if full else 0}
        if target_node:
            kwargs["target"] = target_node
        if target_storage:
            kwargs["storage"] = target_storage
        logger.info("Cloning VM %d to %d (%s) on %s", vmid, newid, name, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).clone.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def migrate_vm(
    vmid: int, target_node: str, node: str | None = None, online: bool = True
) -> dict:
    """Live-migrate a QEMU VM to another node.

    Args:
        vmid: The VM ID to migrate.
        target_node: Destination node.
        node: Source node. Auto-detected if omitted.
        online: True for live migration (default), False for offline.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("migrate_vm", vmid=vmid, target=target_node, node=node)
        logger.info("Migrating VM %d from %s to %s (online=%s)", vmid, node, target_node, online)
        upid = await client.api_call(
            client.api.nodes(node).qemu(vmid).migrate.post,
            target=target_node,
            online=1 if online else 0,
        )
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


# Valid PVE QEMU ostype values (subset); a bare "win" is rejected by the API.
_VALID_OSTYPES = {
    "wxp",
    "w2k",
    "w2k3",
    "w2k8",
    "wvista",
    "win7",
    "win8",
    "win10",
    "win11",
    "l24",
    "l26",
    "l10",
    "l11",
    "solaris",
    "nos",
    "other",
}


@mcp.tool()
async def create_vm(
    node: str,
    name: str,
    vmid: int | None = None,
    memory: int = 2048,
    cores: int = 2,
    sockets: int = 1,
    iso: str | None = None,
    disk_size: str = "32",
    storage: str = "local-lvm",
    net_bridge: str = "vmbr0",
    os_type: str = "l26",
    start_after_create: bool = False,
) -> dict:
    """Create a new QEMU VM.

    Args:
        node: Node to create the VM on.
        name: VM name.
        vmid: Specific VMID, or None to auto-assign.
        memory: RAM in MB (default 2048).
        cores: CPU cores (default 2).
        sockets: CPU sockets (default 1).
        iso: ISO image path for CD-ROM (e.g. 'local:iso/ubuntu.iso').
        disk_size: Root disk size (default '32').
        storage: Storage pool for disks (default 'local-lvm').
        net_bridge: Network bridge (default 'vmbr0').
        os_type: OS type identifier. One of: 'l26' (default, Linux 2.6+),
            'l20' (Linux 2.0-2.6), 'l10' (Linux 1.x), 'win10', 'win11',
            'win7', 'win8', 'w2k8', 'wxp', 'w2k', 'w2k3', 'wvista',
            'solaris' (Solaris), 'nos' (no OS), or 'other'. (No bare 'win'.)
        start_after_create: Start the VM after creation (default False).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        if vmid is not None:
            validate_vmid(vmid)
        if os_type not in _VALID_OSTYPES:
            return {
                "status": "error",
                "message": (
                    f"Unknown os_type {os_type!r}. Valid values: "
                    f"{', '.join(sorted(_VALID_OSTYPES))}."
                ),
            }
        if client.is_dry_run:
            return client.dry_run_response("create_vm", node=node, name=name, vmid=vmid)
        kwargs: dict[str, Any] = {
            "name": name,
            "memory": memory,
            "cores": cores,
            "sockets": sockets,
            "ostype": os_type,
            "scsi0": f"{storage}:{disk_size}",
            "scsihw": "virtio-scsi-single",
            "net0": f"virtio,bridge={net_bridge}",
            "start": 1 if start_after_create else 0,
        }
        if vmid is not None:
            kwargs["vmid"] = vmid
        if iso:
            kwargs["cdrom"] = iso
        logger.info("Creating VM '%s' on %s", name, node)
        upid = await client.api_call(client.api.nodes(node).qemu.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_vm(
    vmid: int,
    node: str | None = None,
    purge: bool = True,
    destroy_unreferenced_disks: bool = True,
    confirm: bool = False,
) -> dict:
    """Permanently delete/destroy a QEMU VM. Set confirm=True to execute.

    Args:
        vmid: The VM ID to delete.
        node: The node name. Auto-detected if omitted.
        purge: Remove from all configurations (default True).
        destroy_unreferenced_disks: Delete associated disks (default True).
        confirm: Must be True to actually delete. False returns a confirmation prompt.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if not confirm:
            vm_data = await client.api_call(client.api.nodes(node).qemu(vmid).status.current.get)
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will PERMANENTLY DELETE VM {vmid} ({vm_data.get('name', 'unnamed')}). "
                    f"All disks and data will be destroyed. This cannot be undone."
                ),
                "action": "Call delete_vm again with confirm=True to proceed.",
                "vm_info": {
                    "vmid": vmid,
                    "name": vm_data.get("name"),
                    "node": node,
                    "status": vm_data.get("status"),
                },
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_vm", vmid=vmid, node=node)
        kwargs: dict[str, Any] = {}
        if purge:
            kwargs["purge"] = 1
        if destroy_unreferenced_disks:
            kwargs["destroy-unreferenced-disks"] = 1
        # NOTE: proxmoxer has no .delete for this endpoint; .delete on the VM
        # resource object issues the GET-based DELETE the API expects here.
        logger.warning("DELETING VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).delete, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def resize_vm_disk(
    vmid: int,
    disk: str,
    size: str,
    node: str | None = None,
) -> dict:
    """Resize a VM disk. Can only grow disks, not shrink.

    Args:
        vmid: The VM ID.
        disk: Disk name (e.g. 'scsi0', 'virtio0', 'ide0', 'sata0').
        size: New absolute size (e.g. '50G') or relative increase (e.g. '+10G').
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response(
                "resize_vm_disk", vmid=vmid, disk=disk, size=size, node=node
            )
        logger.info("Resizing disk '%s' on VM %d to %s", disk, vmid, size)
        await client.api_call(client.api.nodes(node).qemu(vmid).resize.put, disk=disk, size=size)
        return {
            "status": "success",
            "vmid": vmid,
            "node": node,
            "disk": disk,
            "size": size,
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def convert_vm_to_template(
    vmid: int,
    node: str | None = None,
    confirm: bool = False,
) -> dict:
    """Convert a VM to a template. This is irreversible. Set confirm=True to execute.

    Args:
        vmid: The VM ID to convert.
        node: The node name. Auto-detected if omitted.
        confirm: Must be True to execute. False returns a confirmation prompt.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will convert VM {vmid} to a template. "
                    f"This action is IRREVERSIBLE. The VM will no longer be startable."
                ),
                "action": "Call convert_vm_to_template again with confirm=True.",
            }
        if client.is_dry_run:
            return client.dry_run_response("convert_vm_to_template", vmid=vmid, node=node)
        logger.warning("Converting VM %d to template on %s", vmid, node)
        await client.api_call(client.api.nodes(node).qemu(vmid).template.post)
        return {
            "status": "success",
            "vmid": vmid,
            "node": node,
            "message": f"VM {vmid} has been converted to a template.",
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def modify_vm_config(
    vmid: int,
    node: str | None = None,
    memory: int | None = None,
    cores: int | None = None,
    sockets: int | None = None,
    name: str | None = None,
    description: str | None = None,
    balloon: int | None = None,
    cpu_type: str | None = None,
    onboot: bool | None = None,
    tags: str | None = None,
    extra_config: str | None = None,
) -> dict:
    """Modify QEMU VM configuration.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
        memory: RAM in MB.
        cores: CPU cores.
        sockets: CPU sockets.
        name: VM name.
        description: VM description.
        balloon: Balloon memory in MB (0 to disable).
        cpu_type: CPU type (e.g. 'host', 'kvm64').
        onboot: Start on boot.
        tags: Semicolon-separated tags.
        extra_config: JSON string of additional config key/value pairs. Only
            keys in VM_SAFE_CONFIG_KEYS are allowed (e.g. 'cores', 'memory',
            'boot', 'ipconfig0', 'onboot', 'tags' - see VM_SAFE_CONFIG_KEYS
            in this module); all other keys are rejected.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("modify_vm_config", vmid=vmid, node=node)
        kwargs: dict[str, Any] = {}
        if memory is not None:
            kwargs["memory"] = int(memory)
        if cores is not None:
            kwargs["cores"] = int(cores)
        if sockets is not None:
            kwargs["sockets"] = int(sockets)
        if name is not None:
            kwargs["name"] = name
        if description is not None:
            kwargs["description"] = description
        if balloon is not None:
            kwargs["balloon"] = int(balloon)
        if cpu_type is not None:
            kwargs["cpu"] = cpu_type
        if onboot is not None:
            kwargs["onboot"] = 1 if onboot else 0
        if tags is not None:
            kwargs["tags"] = tags
        if extra_config:
            extra = json.loads(extra_config)
            for _key, _val in extra.items():
                if isinstance(_val, str) and len(_val) > MAX_EXTRA_CONFIG_VALUE_LEN:
                    return format_error_response(
                        InvalidParameterError(
                            f"extra_config value for key '{_key}' exceeds "
                            f"{MAX_EXTRA_CONFIG_VALUE_LEN} characters."
                        )
                    )
            unsafe_keys = [k for k in extra if k not in VM_SAFE_CONFIG_KEYS]
            if unsafe_keys:
                return format_error_response(
                    InvalidParameterError(
                        f"Keys not in allowlist: {unsafe_keys}. "
                        f"Modifying these keys is restricted for safety."
                    )
                )
            kwargs.update(extra)
        if not kwargs:
            return {
                "status": "error",
                "error_type": "InvalidParameterError",
                "message": "No configuration changes specified.",
            }
        logger.info("Modifying VM %d config on %s: %s", vmid, node, list(kwargs.keys()))
        await client.api_call(client.api.nodes(node).qemu(vmid).config.put, **kwargs)
        return {"status": "success", "vmid": vmid, "node": node, "changes": list(kwargs.keys())}
    except json.JSONDecodeError:
        return format_error_response(
            InvalidParameterError("extra_config must be valid JSON"),
            suggestion='Example: \'{"boot": "order=scsi0;net0"}\'',
        )
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def set_vm_cloudinit(
    vmid: int,
    node: str | None = None,
    ciuser: str | None = None,
    cipassword: str | None = None,
    sshkeys: str | None = None,
    ipconfig0: str | None = None,
    ipconfig1: str | None = None,
    nameserver: str | None = None,
    searchdomain: str | None = None,
) -> dict:
    """Configure cloud-init settings for a VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
        ciuser: Default user name.
        cipassword: Password for the default user.
        sshkeys: SSH public keys (PEM format), newline-separated.
        ipconfig0: IP config for first interface (e.g. 'ip=dhcp' or
            'ip=10.0.0.5/24,gw=10.0.0.1').
        ipconfig1: IP config for second interface.
        nameserver: DNS server(s), space-separated.
        searchdomain: DNS search domain(s), space-separated.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("set_vm_cloudinit", vmid=vmid, node=node)
        kwargs: dict[str, Any] = {}
        if ciuser is not None:
            kwargs["ciuser"] = ciuser
        if cipassword is not None:
            kwargs["cipassword"] = cipassword
        if sshkeys is not None:
            kwargs["sshkeys"] = sshkeys
        if ipconfig0 is not None:
            kwargs["ipconfig0"] = ipconfig0
        if ipconfig1 is not None:
            kwargs["ipconfig1"] = ipconfig1
        if nameserver is not None:
            kwargs["nameserver"] = nameserver
        if searchdomain is not None:
            kwargs["searchdomain"] = searchdomain
        if not kwargs:
            return format_error_response(InvalidParameterError("No cloud-init settings specified."))
        logger.info("Setting cloud-init on VM %d: %s", vmid, list(kwargs.keys()))
        await client.api_call(client.api.nodes(node).qemu(vmid).config.put, **kwargs)
        return {
            "status": "success",
            "vmid": vmid,
            "node": node,
            "changes": list(kwargs.keys()),
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def regenerate_cloudinit_image(vmid: int, node: str | None = None) -> dict:
    """Regenerate the cloud-init image for a VM.

    Call this after changing cloud-init settings to apply them.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("regenerate_cloudinit_image", vmid=vmid, node=node)
        logger.info("Regenerating cloud-init image for VM %d on %s", vmid, node)
        await client.api_call(client.api.nodes(node).qemu(vmid).cloudinit.post)
        return {
            "status": "success",
            "vmid": vmid,
            "node": node,
            "message": "Cloud-init image regenerated.",
        }
    except Exception as e:
        return format_error_response(e)
