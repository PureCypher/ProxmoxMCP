"""PCI passthrough and cluster hardware mapping tools for Proxmox VE."""

import logging
from typing import TYPE_CHECKING

from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_node_name

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from proxmox_mcp.client import ProxmoxClient

logger = logging.getLogger("proxmox-mcp")


def get_client() -> "ProxmoxClient":
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp() -> "FastMCP":
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()


@mcp.tool()
async def list_node_pci_devices(node: str) -> dict:
    """List PCI devices on a node, including IOMMU group (needed for passthrough).

    Args:
        node: The node name.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        devices = await client.api_call(client.api.nodes(node).hardware.pci.get)
        return {"status": "success", "node": node, "total": len(devices), "devices": devices}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def list_pci_mappings() -> dict:
    """List cluster-wide PCI hardware mappings."""
    try:
        client = get_client()
        mappings = await client.api_call(client.api.cluster.mapping.pci.get)
        return {"status": "success", "total": len(mappings), "mappings": mappings}
    except Exception as e:
        return format_error_response(e)
