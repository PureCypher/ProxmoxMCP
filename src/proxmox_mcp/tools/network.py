"""Network and firewall management tools."""

import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name

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
async def get_node_firewall_rules(node: str) -> dict:
    """List firewall rules configured on a node.

    Args:
        node: The node name.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).firewall.rules.get)
        return {"status": "success", "node": node, "rules": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_vm_firewall_rules(vmid: int, node: str | None = None) -> dict:
    """List firewall rules for a specific VM or container.

    Args:
        vmid: The VM/CT ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        # Try QEMU first, fall back to LXC
        try:
            data = await client.api_call(client.api.nodes(node).qemu(vmid).firewall.rules.get)
        except Exception:
            data = await client.api_call(client.api.nodes(node).lxc(vmid).firewall.rules.get)
        return {"status": "success", "vmid": vmid, "node": node, "rules": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_vm_interfaces(vmid: int, node: str | None = None) -> dict:
    """Get network interfaces of a running VM or container (requires guest agent for VMs).

    Args:
        vmid: The VM/CT ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        # Try QEMU agent first, fall back to LXC interfaces
        try:
            data = await client.api_call(
                client.api.nodes(node).qemu(vmid).agent("network-get-interfaces").get
            )
            interfaces = data.get("result", data)
        except Exception:
            data = await client.api_call(client.api.nodes(node).lxc(vmid).interfaces.get)
            interfaces = data
        return {"status": "success", "vmid": vmid, "node": node, "interfaces": interfaces}
    except Exception as e:
        return format_error_response(e, suggestion="VM must be running. QEMU VMs require the guest agent.")
