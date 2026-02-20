"""QEMU/KVM VM management tools."""

import json
import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name
from proxmox_mcp.utils.formatters import format_vm_summary, format_task_result

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()


async def _resolve_node(client, vmid: int, node: str | None) -> str:
    """Resolve node for a VMID, auto-detecting if not provided."""
    if node:
        validate_node_name(node)
        client.validate_node(node)
        return node
    return await client.resolve_node_for_vmid(vmid)


@mcp.tool()
async def list_vms(node: str | None = None, status_filter: str | None = None) -> dict:
    """List all QEMU VMs across the cluster or on a specific node.

    Args:
        node: Filter to a specific node. None for all nodes.
        status_filter: Filter by status - 'running', 'stopped', or None for all.
    """
    try:
        client = get_client()
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
        node = await _resolve_node(client, vmid, node)
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
        node = await _resolve_node(client, vmid, node)
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
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
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
async def start_vm(vmid: int, node: str | None = None, timeout: int = 60) -> dict:
    """Start a stopped QEMU VM.

    Args:
        vmid: The VM ID to start.
        node: The node name. Auto-detected if omitted.
        timeout: Timeout in seconds (default 60).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("start_vm", vmid=vmid, node=node)
        logger.info("Starting VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.start.post)
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
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("stop_vm", vmid=vmid, node=node)
        logger.warning("Hard stopping VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.stop.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def shutdown_vm(vmid: int, node: str | None = None, timeout: int = 120) -> dict:
    """Graceful ACPI shutdown of a QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
        timeout: Timeout in seconds for the shutdown (default 120).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("shutdown_vm", vmid=vmid, node=node)
        logger.info("Graceful shutdown of VM %d on %s", vmid, node)
        upid = await client.api_call(
            client.api.nodes(node).qemu(vmid).status.shutdown.post, timeout=timeout
        )
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
        node = await _resolve_node(client, vmid, node)
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
        node = await _resolve_node(client, vmid, node)
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
        node = await _resolve_node(client, vmid, node)
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
        node = await _resolve_node(client, vmid, node)
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
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("clone_vm", vmid=vmid, newid=newid, name=name, node=node)
        kwargs = {"newid": newid, "name": name, "full": 1 if full else 0}
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
        node = await _resolve_node(client, vmid, node)
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


@mcp.tool()
async def create_vm(
    node: str,
    name: str,
    vmid: int | None = None,
    memory: int = 2048,
    cores: int = 2,
    sockets: int = 1,
    iso: str | None = None,
    disk_size: str = "32G",
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
        disk_size: Root disk size (default '32G').
        storage: Storage pool for disks (default 'local-lvm').
        net_bridge: Network bridge (default 'vmbr0').
        os_type: OS type identifier (default 'l26' for Linux 2.6+).
        start_after_create: Start the VM after creation (default False).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        if vmid is not None:
            validate_vmid(vmid)
        if client.is_dry_run:
            return client.dry_run_response("create_vm", node=node, name=name, vmid=vmid)
        kwargs = {
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
        node = await _resolve_node(client, vmid, node)
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
        kwargs = {}
        if purge:
            kwargs["purge"] = 1
        if destroy_unreferenced_disks:
            kwargs["destroy-unreferenced-disks"] = 1
        logger.warning("DELETING VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).delete, **kwargs)
        return format_task_result({"data": upid})
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
        extra_config: JSON string of additional config key/value pairs.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("modify_vm_config", vmid=vmid, node=node)
        kwargs = {}
        if memory is not None:
            kwargs["memory"] = memory
        if cores is not None:
            kwargs["cores"] = cores
        if sockets is not None:
            kwargs["sockets"] = sockets
        if name is not None:
            kwargs["name"] = name
        if description is not None:
            kwargs["description"] = description
        if balloon is not None:
            kwargs["balloon"] = balloon
        if cpu_type is not None:
            kwargs["cpu"] = cpu_type
        if onboot is not None:
            kwargs["onboot"] = 1 if onboot else 0
        if tags is not None:
            kwargs["tags"] = tags
        if extra_config:
            extra = json.loads(extra_config)
            # Prevent overriding safety-relevant parameters
            blocked_keys = {"vmid", "node", "digest"}
            extra = {k: v for k, v in extra.items() if k not in blocked_keys}
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
            Exception("extra_config must be valid JSON"),
            suggestion='Example: \'{"boot": "order=scsi0;net0"}\'',
        )
    except Exception as e:
        return format_error_response(e)
