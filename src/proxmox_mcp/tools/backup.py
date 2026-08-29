"""Backup and snapshot management tools."""

import logging
import re
from typing import TYPE_CHECKING, Any

from proxmox_mcp.utils.errors import InvalidParameterError, format_error_response
from proxmox_mcp.utils.formatters import format_task_result
from proxmox_mcp.utils.sanitizers import validate_snapname
from proxmox_mcp.utils.validators import validate_node_name, validate_vmid

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from proxmox_mcp.client import ProxmoxClient

logger = logging.getLogger("proxmox-mcp")


def get_client() -> "ProxmoxClient":
    from proxmox_mcp.server import get_server_client

    return get_server_client()


def get_mcp() -> "FastMCP":
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()

VALID_VM_TYPES = frozenset({"qemu", "lxc"})

VALID_SCHEDULE_PERIODS = frozenset({"hourly", "daily", "weekly", "monthly"})
_AT_TIME_RE = re.compile(r"^at (\d{1,2}):(\d{2})$")


def _validate_vm_type(vm_type: str) -> None:
    if vm_type not in VALID_VM_TYPES:
        raise InvalidParameterError(f"vm_type must be 'qemu' or 'lxc', got '{vm_type}'.")


def _validate_schedule(schedule: str) -> None:
    """Validate a PVE backup-job schedule ('hourly'|'daily'|'weekly'|'monthly'|'at HH:mm')."""
    if schedule in VALID_SCHEDULE_PERIODS:
        return
    m = _AT_TIME_RE.match(schedule)
    if m and 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59:
        return
    raise InvalidParameterError(
        f"Invalid schedule '{schedule}'. Must be one of hourly, daily, weekly, "
        f"monthly, or 'at HH:mm' (e.g. 'at 02:00')."
    )


@mcp.tool()
async def create_snapshot(
    vmid: int,
    snapname: str,
    node: str | None = None,
    description: str | None = None,
    include_vmstate: bool = False,
    vm_type: str = "qemu",
) -> dict:
    """Create a snapshot of a VM or container.

    Args:
        vmid: The VM/CT ID.
        snapname: Name for the snapshot.
        node: The node name. Auto-detected if omitted.
        description: Snapshot description (optional).
        include_vmstate: Include VM RAM state - QEMU only (default False).
        vm_type: 'qemu' for VMs or 'lxc' for containers (default 'qemu').
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_snapname(snapname)
        _validate_vm_type(vm_type)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("create_snapshot", vmid=vmid, snapname=snapname)
        kwargs: dict[str, Any] = {"snapname": snapname}
        if description:
            kwargs["description"] = description
        if include_vmstate and vm_type == "qemu":
            kwargs["vmstate"] = 1
        api_path = (
            client.api.nodes(node).qemu(vmid)
            if vm_type == "qemu"
            else client.api.nodes(node).lxc(vmid)
        )
        logger.info("Creating snapshot '%s' for %s %d", snapname, vm_type, vmid)
        upid = await client.api_call(api_path.snapshot.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def list_snapshots(vmid: int, node: str | None = None, vm_type: str = "qemu") -> dict:
    """List all snapshots of a VM or container.

    Args:
        vmid: The VM/CT ID.
        node: The node name. Auto-detected if omitted.
        vm_type: 'qemu' or 'lxc' (default 'qemu').
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        _validate_vm_type(vm_type)
        node = await client.resolve_node(vmid, node)
        api_path = (
            client.api.nodes(node).qemu(vmid)
            if vm_type == "qemu"
            else client.api.nodes(node).lxc(vmid)
        )
        data = await client.api_call(api_path.snapshot.get)
        return {"status": "success", "vmid": vmid, "node": node, "snapshots": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def rollback_snapshot(
    vmid: int,
    snapname: str,
    node: str | None = None,
    vm_type: str = "qemu",
    confirm: bool = False,
) -> dict:
    """Rollback a VM/CT to a snapshot. Set confirm=True to execute.

    Args:
        vmid: The VM/CT ID.
        snapname: The snapshot name to rollback to.
        node: The node name. Auto-detected if omitted.
        vm_type: 'qemu' or 'lxc' (default 'qemu').
        confirm: Must be True to execute the rollback.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_snapname(snapname)
        _validate_vm_type(vm_type)
        client.check_protected(vmid)
        node = await client.resolve_node(vmid, node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will rollback {vm_type} {vmid} to snapshot '{snapname}'. "
                    f"Current state will be lost."
                ),
                "action": "Call rollback_snapshot again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("rollback_snapshot", vmid=vmid, snapname=snapname)
        api_path = (
            client.api.nodes(node).qemu(vmid)
            if vm_type == "qemu"
            else client.api.nodes(node).lxc(vmid)
        )
        logger.warning("Rolling back %s %d to snapshot '%s'", vm_type, vmid, snapname)
        upid = await client.api_call(api_path.snapshot(snapname).rollback.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_snapshot(
    vmid: int,
    snapname: str,
    node: str | None = None,
    vm_type: str = "qemu",
    confirm: bool = False,
) -> dict:
    """Delete a snapshot. Set confirm=True to execute.

    Args:
        vmid: The VM/CT ID.
        snapname: The snapshot name to delete.
        node: The node name. Auto-detected if omitted.
        vm_type: 'qemu' or 'lxc' (default 'qemu').
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_snapname(snapname)
        _validate_vm_type(vm_type)
        node = await client.resolve_node(vmid, node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete snapshot '{snapname}' from {vm_type} {vmid}.",
                "action": "Call delete_snapshot again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_snapshot", vmid=vmid, snapname=snapname)
        api_path = (
            client.api.nodes(node).qemu(vmid)
            if vm_type == "qemu"
            else client.api.nodes(node).lxc(vmid)
        )
        logger.warning("Deleting snapshot '%s' from %s %d", snapname, vm_type, vmid)
        upid = await client.api_call(api_path.snapshot(snapname).delete)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def create_backup(
    vmid: int,
    node: str | None = None,
    storage: str = "local",
    mode: str = "snapshot",
    compress: str = "zstd",
    notes: str | None = None,
) -> dict:
    """Initiate a vzdump backup of a VM or container.

    Args:
        vmid: The VM/CT ID to backup.
        node: The node name. Auto-detected if omitted.
        storage: Target storage for the backup (default 'local').
        mode: Backup mode - 'snapshot', 'suspend', or 'stop' (default 'snapshot').
        compress: Compression - 'zstd', 'lzo', 'gzip', or 'none' (default 'zstd').
        notes: Backup notes (optional).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("create_backup", vmid=vmid, storage=storage)
        kwargs: dict[str, Any] = {
            "vmid": vmid,
            "storage": storage,
            "mode": mode,
            "compress": compress,
        }
        if notes:
            kwargs["notes-template"] = notes
        logger.info("Starting backup of VMID %d on %s (mode=%s)", vmid, node, mode)
        upid = await client.api_call(client.api.nodes(node).vzdump.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def list_backups(node: str, storage: str = "local", vmid: int | None = None) -> dict:
    """List available backups in a storage pool.

    Args:
        node: The node name.
        storage: The storage pool (default 'local').
        vmid: Filter backups for a specific VMID (optional).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        kwargs: dict[str, Any] = {"content": "backup"}
        data = await client.api_call(client.api.nodes(node).storage(storage).content.get, **kwargs)
        if vmid is not None:
            vmid_str = str(vmid)
            data = [
                b
                for b in data
                if f"-{vmid_str}-" in b.get("volid", "")
                or b.get("volid", "").endswith(f"-{vmid_str}")
            ]
        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "backups": data,
            "total": len(data),
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def restore_backup(
    node: str,
    storage: str,
    archive: str,
    vmid: int,
    force: bool = False,
    confirm: bool = False,
) -> dict:
    """Restore a VM/CT from a backup archive. Set confirm=True to execute.

    Args:
        node: The node to restore onto.
        storage: Target storage for the restored disks.
        archive: The backup archive path/volid.
        vmid: VMID for the restored VM/CT.
        force: Overwrite existing VMID if it exists (default False).
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_node_name(node)
        validate_vmid(vmid)
        client.validate_node(node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will restore backup '{archive}' as VMID {vmid} on {node}.",
                "action": "Call restore_backup again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("restore_backup", archive=archive, vmid=vmid, node=node)
        # Detect type from archive name
        if archive.startswith("vzdump-lxc-") or "/vzdump-lxc-" in archive:
            kwargs: dict[str, Any] = {
                "ostemplate": archive,
                "vmid": vmid,
                "storage": storage,
                "restore": 1,
            }
            if force:
                kwargs["force"] = 1
            logger.warning("Restoring LXC backup %s as VMID %d on %s", archive, vmid, node)
            upid = await client.api_call(client.api.nodes(node).lxc.post, **kwargs)
        else:
            kwargs = {"archive": archive, "vmid": vmid, "storage": storage}
            if force:
                kwargs["force"] = 1
            logger.warning("Restoring QEMU backup %s as VMID %d on %s", archive, vmid, node)
            upid = await client.api_call(client.api.nodes(node).qemu.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Backup job scheduling
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_backup_jobs() -> dict:
    """List all scheduled backup jobs in the cluster.

    Returns each job's ID, schedule, target storage, included VMs, and settings.
    """
    try:
        client = get_client()
        logger.info("Listing scheduled backup jobs")
        data = await client.api_call(client.api.cluster.backup.get)
        return {"status": "success", "count": len(data), "jobs": data}
    except Exception as e:
        logger.error("Failed to list backup jobs: %s", e)
        return format_error_response(e)


@mcp.tool()
async def create_backup_job(
    storage: str,
    schedule: str,
    vmid: str | None = None,
    all_vms: bool = False,
    mode: str = "snapshot",
    compress: str = "zstd",
    mailnotification: str | None = None,
    mailto: str | None = None,
    enabled: bool = True,
    comment: str | None = None,
) -> dict:
    """Create a scheduled backup job.

    Args:
        storage: Target storage for backups (e.g. 'local', 'nfs-backup').
        schedule: PVE backup schedule - one of 'hourly', 'daily', 'weekly',
            'monthly', or 'at HH:mm' (e.g. 'at 02:00').
        vmid: Comma-separated VMIDs to back up (e.g. '100,101,102').
        all_vms: Back up all VMs/CTs (overrides vmid).
        mode: Backup mode - 'snapshot', 'suspend', or 'stop' (default 'snapshot').
        compress: Compression - 'zstd', 'lzo', 'gzip', or 'none' (default 'zstd').
        mailnotification: Email notification - 'always' or 'failure'.
        mailto: Comma-separated email addresses for notifications.
        enabled: Enable the job (default True).
        comment: Job description/comment.
    """
    try:
        client = get_client()
        _validate_schedule(schedule)
        if client.is_dry_run:
            return client.dry_run_response("create_backup_job", storage=storage, schedule=schedule)
        kwargs: dict[str, Any] = {
            "storage": storage,
            "schedule": schedule,
            "mode": mode,
            "compress": compress,
            "enabled": 1 if enabled else 0,
        }
        if all_vms:
            kwargs["all"] = 1
        elif vmid:
            kwargs["vmid"] = vmid
        if mailnotification:
            kwargs["mailnotification"] = mailnotification
        if mailto:
            kwargs["mailto"] = mailto
        if comment:
            kwargs["comment"] = comment
        logger.info("Creating backup job: storage=%s, schedule=%s", storage, schedule)
        await client.api_call(client.api.cluster.backup.post, **kwargs)
        return {
            "status": "success",
            "message": "Backup job created successfully.",
            "storage": storage,
            "schedule": schedule,
        }
    except Exception as e:
        logger.error("Failed to create backup job: %s", e)
        return format_error_response(e)


@mcp.tool()
async def delete_backup_job(
    job_id: str,
    confirm: bool = False,
) -> dict:
    """Delete a scheduled backup job. Set confirm=True to execute.

    Args:
        job_id: The backup job ID (from list_backup_jobs).
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete backup job '{job_id}'.",
                "action": "Call delete_backup_job with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_backup_job", job_id=job_id)
        logger.warning("Deleting backup job '%s'", job_id)
        await client.api_call(client.api.cluster.backup(job_id).delete)
        return {
            "status": "success",
            "job_id": job_id,
            "message": f"Backup job '{job_id}' deleted.",
        }
    except Exception as e:
        logger.error("Failed to delete backup job '%s': %s", job_id, e)
        return format_error_response(e)
