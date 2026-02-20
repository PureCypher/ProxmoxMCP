"""Cluster-level read-only tools for Proxmox VE."""

import logging
from proxmox_mcp.utils.errors import format_error_response

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.tool()
async def get_cluster_status() -> dict:
    """Get the overall cluster status including cluster info and node membership.

    Returns cluster-level information (name, quorum, version) and a list of all
    nodes with their online/offline status.
    """
    try:
        client = get_client()
        logger.info("Fetching cluster status")
        data = await client.api_call(client.api.cluster.status.get)

        cluster_info = {}
        nodes = []
        for item in data:
            if item.get("type") == "cluster":
                cluster_info = {
                    "name": item.get("name"),
                    "version": item.get("version"),
                    "quorate": item.get("quorate"),
                    "nodes": item.get("nodes"),
                }
            elif item.get("type") == "node":
                nodes.append({
                    "name": item.get("name"),
                    "id": item.get("id"),
                    "online": item.get("online"),
                    "ip": item.get("ip"),
                    "level": item.get("level", ""),
                    "local": item.get("local", 0),
                })

        return {
            "status": "success",
            "cluster": cluster_info,
            "nodes": nodes,
        }
    except Exception as e:
        logger.error(f"Failed to get cluster status: {e}")
        return format_error_response(e)


@mcp.tool()
async def get_cluster_resources(resource_type: str | None = None) -> dict:
    """Get all resources across the cluster with optional type filtering.

    Args:
        resource_type: Optional filter - one of 'vm', 'storage', 'node', 'sdn'.
                       If not provided, returns all resource types.
    """
    try:
        client = get_client()
        logger.info(f"Fetching cluster resources (type={resource_type})")
        kwargs = {}
        if resource_type:
            kwargs["type"] = resource_type
        data = await client.api_call(client.api.cluster.resources.get, **kwargs)

        return {
            "status": "success",
            "resource_type": resource_type or "all",
            "count": len(data),
            "resources": data,
        }
    except Exception as e:
        logger.error(f"Failed to get cluster resources: {e}")
        return format_error_response(e)


@mcp.tool()
async def get_cluster_log(max_entries: int = 50) -> dict:
    """Get recent cluster log entries.

    Args:
        max_entries: Maximum number of log entries to return (default: 50).
    """
    try:
        client = get_client()
        logger.info(f"Fetching cluster log (max_entries={max_entries})")
        data = await client.api_call(client.api.cluster.log.get, max=max_entries)

        return {
            "status": "success",
            "count": len(data),
            "entries": data,
        }
    except Exception as e:
        logger.error(f"Failed to get cluster log: {e}")
        return format_error_response(e)


@mcp.tool()
async def get_next_vmid() -> dict:
    """Get the next available VMID from the cluster.

    Returns the next free VMID that can be used when creating a new VM or container.
    """
    try:
        client = get_client()
        logger.info("Fetching next available VMID")
        data = await client.api_call(client.api.cluster.nextid.get)

        return {
            "status": "success",
            "vmid": int(data),
        }
    except Exception as e:
        logger.error(f"Failed to get next VMID: {e}")
        return format_error_response(e)


@mcp.tool()
async def list_pools() -> dict:
    """List all resource pools in the cluster.

    Returns a list of pools with their comments and member counts.
    """
    try:
        client = get_client()
        logger.info("Fetching resource pools")
        data = await client.api_call(client.api.pools.get)

        return {
            "status": "success",
            "count": len(data),
            "pools": data,
        }
    except Exception as e:
        logger.error(f"Failed to list pools: {e}")
        return format_error_response(e)
