"""Node-level read-only tools for Proxmox VE."""

import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.formatters import format_bytes, format_uptime
from proxmox_mcp.utils.validators import validate_node_name

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()


@mcp.tool()
async def list_nodes() -> dict:
    """List all nodes in the Proxmox cluster with their status and resource usage.

    Returns each node's name, status, CPU/memory usage, and uptime in
    human-readable format.
    """
    try:
        client = get_client()
        logger.info("Listing all cluster nodes")
        data = await client.api_call(client.api.nodes.get)

        nodes = []
        for node in data:
            nodes.append(
                {
                    "node": node.get("node"),
                    "status": node.get("status"),
                    "cpu_usage_percent": round(node.get("cpu", 0) * 100, 2),
                    "cpu_cores": node.get("maxcpu", 0),
                    "memory_used": format_bytes(node.get("mem", 0)),
                    "memory_total": format_bytes(node.get("maxmem", 0)),
                    "disk_used": format_bytes(node.get("disk", 0)),
                    "disk_total": format_bytes(node.get("maxdisk", 0)),
                    "uptime": format_uptime(node.get("uptime", 0)),
                    "uptime_seconds": node.get("uptime", 0),
                }
            )

        return {
            "status": "success",
            "count": len(nodes),
            "nodes": nodes,
        }
    except Exception as e:
        logger.error(f"Failed to list nodes: {e}")
        return format_error_response(e)


@mcp.tool()
async def get_node_status(node: str) -> dict:
    """Get detailed status information for a specific node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').

    Returns CPU, memory, swap, disk, uptime, kernel version, and load averages.
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(f"Fetching status for node '{node}'")
        data = await client.api_call(client.api.nodes(node).status.get)

        return {
            "status": "success",
            "node": node,
            "data": data,
        }
    except Exception as e:
        logger.error(f"Failed to get status for node '{node}': {e}")
        return format_error_response(e)


@mcp.tool()
async def get_node_services(node: str) -> dict:
    """List all system services running on a specific node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').

    Returns each service's name, state (running/stopped), and description.
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(f"Fetching services for node '{node}'")
        data = await client.api_call(client.api.nodes(node).services.get)

        return {
            "status": "success",
            "node": node,
            "count": len(data),
            "services": data,
        }
    except Exception as e:
        logger.error(f"Failed to get services for node '{node}': {e}")
        return format_error_response(e)


@mcp.tool()
async def get_node_network(node: str) -> dict:
    """Get network interface configuration for a specific node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').

    Returns all network interfaces with their type, addresses, and settings.
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(f"Fetching network config for node '{node}'")
        data = await client.api_call(client.api.nodes(node).network.get)

        return {
            "status": "success",
            "node": node,
            "count": len(data),
            "interfaces": data,
        }
    except Exception as e:
        logger.error(f"Failed to get network config for node '{node}': {e}")
        return format_error_response(e)


@mcp.tool()
async def get_node_storage(node: str) -> dict:
    """List all storage backends available on a specific node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').

    Returns each storage's name, type, usage, and enabled/active state.
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(f"Fetching storage for node '{node}'")
        data = await client.api_call(client.api.nodes(node).storage.get)

        return {
            "status": "success",
            "node": node,
            "count": len(data),
            "storage": data,
        }
    except Exception as e:
        logger.error(f"Failed to get storage for node '{node}': {e}")
        return format_error_response(e)


@mcp.tool()
async def get_node_syslog(node: str, limit: int = 50, since: str | None = None) -> dict:
    """Read syslog entries from a specific node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        limit: Maximum number of log lines to return (default: 50).
        since: Optional start date/time filter (e.g., '2024-01-01' or '2024-01-01 12:00:00').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(f"Fetching syslog for node '{node}' (limit={limit}, since={since})")

        kwargs = {"limit": limit}
        if since:
            kwargs["since"] = since

        data = await client.api_call(client.api.nodes(node).syslog.get, **kwargs)

        return {
            "status": "success",
            "node": node,
            "count": len(data),
            "entries": data,
        }
    except Exception as e:
        logger.error(f"Failed to get syslog for node '{node}': {e}")
        return format_error_response(e)
