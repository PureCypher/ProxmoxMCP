"""Backup and snapshot management tools."""

import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name
from proxmox_mcp.utils.formatters import format_task_result

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


async def _resolve_node(client, vmid: int, node: str | None) -> str:
    if node:
        validate_node_name(node)
        client.validate_node(node)
        return node
    return await client.resolve_node_for_vmid(vmid)


@mcp.tool()
async def create_snapshot(
    vmid: int, snapname: str, node: str | None = None,
    description: str | None = None, include_vmstate: bool = False,
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
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("create_snapshot", vmid=vmid, snapname=snapname)
        kwargs = {"snapname": snapname}
        if description:
            kwargs["description"] = description
        if include_vmstate and vm_type == "qemu":
            kwargs["vmstate"] = 1
        api_path = client.api.nodes(node).qemu(vmid) if vm_type == "qemu" else client.api.nodes(node).lxc(vmid)
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
        node = await _resolve_node(client, vmid, node)
        api_path = client.api.nodes(node).qemu(vmid) if vm_type == "qemu" else client.api.nodes(node).lxc(vmid)
        data = await client.api_call(api_path.snapshot.get)
        return {"status": "success", "vmid": vmid, "node": node, "snapshots": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def rollback_snapshot(
    vmid: int, snapname: str, node: str | None = None,
    vm_type: str = "qemu", confirm: bool = False,
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
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will rollback {vm_type} {vmid} to snapshot '{snapname}'. Current state will be lost.",
                "action": "Call rollback_snapshot again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("rollback_snapshot", vmid=vmid, snapname=snapname)
        api_path = client.api.nodes(node).qemu(vmid) if vm_type == "qemu" else client.api.nodes(node).lxc(vmid)
        logger.warning("Rolling back %s %d to snapshot '%s'", vm_type, vmid, snapname)
        upid = await client.api_call(api_path.snapshot(snapname).rollback.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_snapshot(
    vmid: int, snapname: str, node: str | None = None,
    vm_type: str = "qemu", confirm: bool = False,
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
        node = await _resolve_node(client, vmid, node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete snapshot '{snapname}' from {vm_type} {vmid}.",
                "action": "Call delete_snapshot again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_snapshot", vmid=vmid, snapname=snapname)
        api_path = client.api.nodes(node).qemu(vmid) if vm_type == "qemu" else client.api.nodes(node).lxc(vmid)
        logger.warning("Deleting snapshot '%s' from %s %d", snapname, vm_type, vmid)
        upid = await client.api_call(api_path.snapshot(snapname).delete)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def create_backup(
    vmid: int, node: str | None = None, storage: str = "local",
    mode: str = "snapshot", compress: str = "zstd", notes: str | None = None,
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
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("create_backup", vmid=vmid, storage=storage)
        kwargs = {
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
        kwargs = {"content": "backup"}
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, **kwargs
        )
        if vmid:
            data = [b for b in data if str(vmid) in b.get("volid", "")]
        return {"status": "success", "node": node, "storage": storage, "backups": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def restore_backup(
    node: str, storage: str, archive: str, vmid: int,
    force: bool = False, confirm: bool = False,
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
        if "lxc" in archive or "ct" in archive:
            kwargs = {"ostemplate": archive, "vmid": vmid, "storage": storage, "restore": 1}
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
