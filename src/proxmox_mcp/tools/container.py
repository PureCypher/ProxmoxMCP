"""LXC container management tools."""

import json
import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name
from proxmox_mcp.utils.formatters import format_container_summary, format_task_result

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
async def list_containers(node: str | None = None, status_filter: str | None = None) -> dict:
    """List all LXC containers across the cluster or on a specific node.

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
        cts = [r for r in resources if r.get("type") == "lxc"]
        if node:
            cts = [c for c in cts if c.get("node") == node]
        if status_filter:
            cts = [c for c in cts if c.get("status") == status_filter]
        formatted = [format_container_summary(c) for c in cts]
        return {"status": "success", "containers": formatted, "total": len(formatted)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_container_status(vmid: int, node: str | None = None) -> dict:
    """Get detailed status of a specific LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        data = await client.api_call(client.api.nodes(node).lxc(vmid).status.current.get)
        return {"status": "success", "vmid": vmid, "node": node, "data": data}
    except Exception as e:
        return format_error_response(e, suggestion="Use list_containers to see available containers.")


@mcp.tool()
async def get_container_config(vmid: int, node: str | None = None) -> dict:
    """Get full configuration of an LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        data = await client.api_call(client.api.nodes(node).lxc(vmid).config.get)
        return {"status": "success", "vmid": vmid, "node": node, "config": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def start_container(vmid: int, node: str | None = None) -> dict:
    """Start a stopped LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("start_container", vmid=vmid, node=node)
        logger.info("Starting container %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).status.start.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def stop_container(vmid: int, node: str | None = None) -> dict:
    """Stop an LXC container immediately.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("stop_container", vmid=vmid, node=node)
        logger.warning("Stopping container %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).status.stop.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def shutdown_container(vmid: int, node: str | None = None, timeout: int = 60) -> dict:
    """Graceful shutdown of an LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
        timeout: Timeout in seconds (default 60).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("shutdown_container", vmid=vmid, node=node)
        logger.info("Graceful shutdown of container %d on %s", vmid, node)
        upid = await client.api_call(
            client.api.nodes(node).lxc(vmid).status.shutdown.post, timeout=timeout
        )
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def reboot_container(vmid: int, node: str | None = None) -> dict:
    """Reboot an LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("reboot_container", vmid=vmid, node=node)
        logger.info("Rebooting container %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).status.reboot.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def clone_container(
    vmid: int, newid: int, name: str, node: str | None = None,
    full: bool = True, target_node: str | None = None,
) -> dict:
    """Clone an LXC container.

    Args:
        vmid: Source container ID.
        newid: New VMID for the clone.
        name: Hostname for the clone.
        node: Source node. Auto-detected if omitted.
        full: Full clone (True) or linked (False).
        target_node: Destination node (optional).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_vmid(newid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("clone_container", vmid=vmid, newid=newid, name=name)
        kwargs = {"newid": newid, "hostname": name, "full": 1 if full else 0}
        if target_node:
            kwargs["target"] = target_node
        logger.info("Cloning container %d to %d on %s", vmid, newid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).clone.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def migrate_container(
    vmid: int, target_node: str, node: str | None = None,
    online: bool = False, restart: bool = True,
) -> dict:
    """Migrate an LXC container to another node.

    Args:
        vmid: The container ID.
        target_node: Destination node.
        node: Source node. Auto-detected if omitted.
        online: Online migration (default False).
        restart: Restart after migration (default True).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("migrate_container", vmid=vmid, target=target_node)
        logger.info("Migrating container %d from %s to %s", vmid, node, target_node)
        upid = await client.api_call(
            client.api.nodes(node).lxc(vmid).migrate.post,
            target=target_node, online=1 if online else 0, restart=1 if restart else 0,
        )
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def create_container(
    node: str, ostemplate: str, hostname: str,
    vmid: int | None = None, password: str | None = None,
    ssh_public_keys: str | None = None, memory: int = 512,
    swap: int = 512, cores: int = 1, rootfs_size: str = "8",
    storage: str = "local-lvm", net_bridge: str = "vmbr0",
    ip_config: str = "dhcp", unprivileged: bool = True,
    start_after_create: bool = False,
) -> dict:
    """Create a new LXC container.

    Args:
        node: Node to create the container on.
        ostemplate: Template path (e.g. 'local:vztmpl/ubuntu-22.04.tar.zst').
        hostname: Container hostname.
        vmid: Specific VMID, or None to auto-assign.
        password: Root password (optional).
        ssh_public_keys: SSH public keys for root (optional).
        memory: RAM in MB (default 512).
        swap: Swap in MB (default 512).
        cores: CPU cores (default 1).
        rootfs_size: Root filesystem size in GB (default '8').
        storage: Storage pool (default 'local-lvm').
        net_bridge: Network bridge (default 'vmbr0').
        ip_config: IP config - 'dhcp' or 'ip=x.x.x.x/xx,gw=x.x.x.x' (default 'dhcp').
        unprivileged: Unprivileged container (default True).
        start_after_create: Start after creation (default False).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        if vmid:
            validate_vmid(vmid)
        if client.is_dry_run:
            return client.dry_run_response("create_container", node=node, hostname=hostname)
        net_value = f"name=eth0,bridge={net_bridge}"
        if ip_config == "dhcp":
            ip_value = "ip=dhcp"
        else:
            ip_value = ip_config
        kwargs = {
            "ostemplate": ostemplate,
            "hostname": hostname,
            "memory": memory,
            "swap": swap,
            "cores": cores,
            "rootfs": f"{storage}:{rootfs_size}",
            "net0": net_value,
            "ipconfig0": ip_value,
            "unprivileged": 1 if unprivileged else 0,
            "start": 1 if start_after_create else 0,
        }
        if vmid:
            kwargs["vmid"] = vmid
        if password:
            kwargs["password"] = password
        if ssh_public_keys:
            kwargs["ssh-public-keys"] = ssh_public_keys
        logger.info("Creating container '%s' on %s", hostname, node)
        upid = await client.api_call(client.api.nodes(node).lxc.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_container(
    vmid: int, node: str | None = None, purge: bool = True,
    force: bool = False, confirm: bool = False,
) -> dict:
    """Permanently delete an LXC container. Set confirm=True to execute.

    Args:
        vmid: The container ID to delete.
        node: The node name. Auto-detected if omitted.
        purge: Remove from all configurations (default True).
        force: Force deletion even if running (default False).
        confirm: Must be True to actually delete.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if not confirm:
            ct_data = await client.api_call(client.api.nodes(node).lxc(vmid).status.current.get)
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will PERMANENTLY DELETE container {vmid} ({ct_data.get('name', 'unnamed')}). "
                    f"This cannot be undone."
                ),
                "action": "Call delete_container again with confirm=True to proceed.",
                "container_info": {"vmid": vmid, "name": ct_data.get("name"), "node": node},
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_container", vmid=vmid, node=node)
        kwargs = {}
        if purge:
            kwargs["purge"] = 1
        if force:
            kwargs["force"] = 1
        logger.warning("DELETING container %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).delete, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def modify_container_config(
    vmid: int, node: str | None = None,
    memory: int | None = None, swap: int | None = None,
    cores: int | None = None, hostname: str | None = None,
    description: str | None = None, onboot: bool | None = None,
    tags: str | None = None, extra_config: str | None = None,
) -> dict:
    """Modify LXC container configuration.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
        memory: RAM in MB.
        swap: Swap in MB.
        cores: CPU cores.
        hostname: Container hostname.
        description: Description.
        onboot: Start on boot.
        tags: Semicolon-separated tags.
        extra_config: JSON string of additional config key/value pairs.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("modify_container_config", vmid=vmid, node=node)
        kwargs = {}
        if memory is not None:
            kwargs["memory"] = memory
        if swap is not None:
            kwargs["swap"] = swap
        if cores is not None:
            kwargs["cores"] = cores
        if hostname is not None:
            kwargs["hostname"] = hostname
        if description is not None:
            kwargs["description"] = description
        if onboot is not None:
            kwargs["onboot"] = 1 if onboot else 0
        if tags is not None:
            kwargs["tags"] = tags
        if extra_config:
            kwargs.update(json.loads(extra_config))
        if not kwargs:
            return {"status": "error", "error_type": "InvalidParameterError",
                    "message": "No configuration changes specified."}
        logger.info("Modifying container %d config: %s", vmid, list(kwargs.keys()))
        await client.api_call(client.api.nodes(node).lxc(vmid).config.put, **kwargs)
        return {"status": "success", "vmid": vmid, "node": node, "changes": list(kwargs.keys())}
    except json.JSONDecodeError:
        return format_error_response(Exception("extra_config must be valid JSON"))
    except Exception as e:
        return format_error_response(e)
