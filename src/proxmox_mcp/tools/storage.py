"""Storage-level read-only tools for Proxmox VE."""

import logging
from proxmox_mcp.utils.errors import format_error_response
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
async def list_storage() -> dict:
    """List all storage backends configured in the Proxmox cluster.

    Returns each storage's name, type, content types, nodes, and shared status.
    """
    try:
        client = get_client()
        logger.info("Listing all cluster storage")
        data = await client.api_call(client.api.storage.get)

        return {
            "status": "success",
            "count": len(data),
            "storage": data,
        }
    except Exception as e:
        logger.error(f"Failed to list storage: {e}")
        return format_error_response(e)


@mcp.tool()
async def get_storage_status(node: str, storage: str) -> dict:
    """Get detailed status and usage information for a specific storage on a node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        storage: The storage identifier (e.g., 'local', 'local-lvm', 'ceph-pool').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(f"Fetching storage status for '{storage}' on node '{node}'")
        data = await client.api_call(
            client.api.nodes(node).storage(storage).status.get
        )

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "data": data,
        }
    except Exception as e:
        logger.error(f"Failed to get storage status for '{storage}' on '{node}': {e}")
        return format_error_response(e)


@mcp.tool()
async def list_storage_content(
    node: str, storage: str, content_type: str | None = None
) -> dict:
    """List the contents of a specific storage on a node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        storage: The storage identifier (e.g., 'local', 'local-lvm').
        content_type: Optional filter for content type (e.g., 'images', 'iso',
                      'vztmpl', 'backup', 'rootdir', 'snippets').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(
            f"Listing content for storage '{storage}' on node '{node}' "
            f"(content_type={content_type})"
        )

        kwargs = {}
        if content_type:
            kwargs["content"] = content_type

        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, **kwargs
        )

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "content_type": content_type or "all",
            "count": len(data),
            "content": data,
        }
    except Exception as e:
        logger.error(
            f"Failed to list content for storage '{storage}' on '{node}': {e}"
        )
        return format_error_response(e)


@mcp.tool()
async def get_available_isos(node: str, storage: str = "local") -> dict:
    """List available ISO images on a specific storage.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        storage: The storage identifier (default: 'local').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(f"Fetching available ISOs from '{storage}' on node '{node}'")
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, content="iso"
        )

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "count": len(data),
            "isos": data,
        }
    except Exception as e:
        logger.error(f"Failed to get ISOs from '{storage}' on '{node}': {e}")
        return format_error_response(e)


@mcp.tool()
async def get_available_templates(node: str, storage: str = "local") -> dict:
    """List available container templates on a specific storage.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        storage: The storage identifier (default: 'local').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(f"Fetching available templates from '{storage}' on node '{node}'")
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, content="vztmpl"
        )

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "count": len(data),
            "templates": data,
        }
    except Exception as e:
        logger.error(f"Failed to get templates from '{storage}' on '{node}': {e}")
        return format_error_response(e)
