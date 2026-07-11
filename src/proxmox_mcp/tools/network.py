"""Network and firewall management tools."""

import logging
from typing import TYPE_CHECKING

from proxmox_mcp.utils.errors import InvalidParameterError, format_error_response
from proxmox_mcp.utils.validators import validate_node_name, validate_vmid

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from proxmox_mcp.client import ProxmoxClient

VALID_FW_ACTIONS = frozenset({"ACCEPT", "DROP", "REJECT"})
VALID_FW_TYPES = frozenset({"in", "out", "group"})

logger = logging.getLogger("proxmox-mcp")


def get_client() -> "ProxmoxClient":
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp() -> "FastMCP":
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()


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
        node = await client.resolve_node(vmid, node)
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
        node = await client.resolve_node(vmid, node)
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
        return format_error_response(
            e, suggestion="VM must be running. QEMU VMs require the guest agent."
        )


@mcp.tool()
async def create_node_firewall_rule(
    node: str,
    action: str,
    type: str,
    enable: bool = True,
    source: str | None = None,
    dest: str | None = None,
    proto: str | None = None,
    dport: str | None = None,
    sport: str | None = None,
    comment: str | None = None,
    pos: int | None = None,
) -> dict:
    """Create a firewall rule on a node.

    Args:
        node: The node name.
        action: Rule action - 'ACCEPT', 'DROP', or 'REJECT'.
        type: Rule type - 'in' (incoming), 'out' (outgoing), or 'group'.
        enable: Enable the rule (default True).
        source: Source address/CIDR (e.g. '10.0.0.0/24').
        dest: Destination address/CIDR.
        proto: Protocol (e.g. 'tcp', 'udp', 'icmp').
        dport: Destination port or range (e.g. '80', '8000-9000').
        sport: Source port or range.
        comment: Rule comment/description.
        pos: Position in rule list (0-based). Appended if omitted.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        if action not in VALID_FW_ACTIONS:
            raise InvalidParameterError(
                f"action must be one of {sorted(VALID_FW_ACTIONS)}, got '{action}'."
            )
        if type not in VALID_FW_TYPES:
            raise InvalidParameterError(
                f"type must be one of {sorted(VALID_FW_TYPES)}, got '{type}'."
            )
        if client.is_dry_run:
            return client.dry_run_response(
                "create_node_firewall_rule", node=node, action=action, type=type
            )
        kwargs: dict = {"action": action, "type": type, "enable": 1 if enable else 0}
        if source:
            kwargs["source"] = source
        if dest:
            kwargs["dest"] = dest
        if proto:
            kwargs["proto"] = proto
        if dport:
            kwargs["dport"] = dport
        if sport:
            kwargs["sport"] = sport
        if comment:
            kwargs["comment"] = comment
        if pos is not None:
            kwargs["pos"] = pos
        logger.info("Creating firewall rule on node '%s': %s %s", node, action, type)
        await client.api_call(client.api.nodes(node).firewall.rules.post, **kwargs)
        return {"status": "success", "node": node, "rule": kwargs}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_node_firewall_rule(
    node: str,
    pos: int,
    confirm: bool = False,
) -> dict:
    """Delete a firewall rule from a node by position. Set confirm=True to execute.

    Args:
        node: The node name.
        pos: Rule position (0-based index from get_node_firewall_rules).
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete firewall rule at position {pos} on node '{node}'.",
                "action": "Call delete_node_firewall_rule with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response(
                "delete_node_firewall_rule", node=node, pos=pos
            )
        logger.warning("Deleting firewall rule %d on node '%s'", pos, node)
        await client.api_call(client.api.nodes(node).firewall.rules(pos).delete)
        return {"status": "success", "node": node, "deleted_pos": pos}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def create_vm_firewall_rule(
    vmid: int,
    action: str,
    type: str,
    node: str | None = None,
    vm_type: str = "qemu",
    enable: bool = True,
    source: str | None = None,
    dest: str | None = None,
    proto: str | None = None,
    dport: str | None = None,
    sport: str | None = None,
    comment: str | None = None,
    pos: int | None = None,
) -> dict:
    """Create a firewall rule on a VM or container.

    Args:
        vmid: The VM/CT ID.
        action: Rule action - 'ACCEPT', 'DROP', or 'REJECT'.
        type: Rule type - 'in' (incoming), 'out' (outgoing), or 'group'.
        node: The node name. Auto-detected if omitted.
        vm_type: 'qemu' for VMs or 'lxc' for containers (default 'qemu').
        enable: Enable the rule (default True).
        source: Source address/CIDR.
        dest: Destination address/CIDR.
        proto: Protocol (e.g. 'tcp', 'udp', 'icmp').
        dport: Destination port or range.
        sport: Source port or range.
        comment: Rule comment/description.
        pos: Position in rule list (0-based).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        if action not in VALID_FW_ACTIONS:
            raise InvalidParameterError(
                f"action must be one of {sorted(VALID_FW_ACTIONS)}, got '{action}'."
            )
        if type not in VALID_FW_TYPES:
            raise InvalidParameterError(
                f"type must be one of {sorted(VALID_FW_TYPES)}, got '{type}'."
            )
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response(
                "create_vm_firewall_rule", vmid=vmid, action=action, type=type
            )
        kwargs: dict = {"action": action, "type": type, "enable": 1 if enable else 0}
        if source:
            kwargs["source"] = source
        if dest:
            kwargs["dest"] = dest
        if proto:
            kwargs["proto"] = proto
        if dport:
            kwargs["dport"] = dport
        if sport:
            kwargs["sport"] = sport
        if comment:
            kwargs["comment"] = comment
        if pos is not None:
            kwargs["pos"] = pos
        api_path = (
            client.api.nodes(node).qemu(vmid)
            if vm_type == "qemu"
            else client.api.nodes(node).lxc(vmid)
        )
        logger.info(
            "Creating firewall rule on %s %d: %s %s", vm_type, vmid, action, type
        )
        await client.api_call(api_path.firewall.rules.post, **kwargs)
        return {"status": "success", "vmid": vmid, "node": node, "rule": kwargs}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_vm_firewall_rule(
    vmid: int,
    pos: int,
    node: str | None = None,
    vm_type: str = "qemu",
    confirm: bool = False,
) -> dict:
    """Delete a firewall rule from a VM/CT by position. Set confirm=True to execute.

    Args:
        vmid: The VM/CT ID.
        pos: Rule position (0-based index).
        node: The node name. Auto-detected if omitted.
        vm_type: 'qemu' for VMs or 'lxc' for containers (default 'qemu').
        confirm: Must be True to execute.
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
                    f"This will delete firewall rule at position {pos} "
                    f"on {vm_type} {vmid}."
                ),
                "action": "Call delete_vm_firewall_rule with confirm=True.",
            }
        if client.is_dry_run:
            return client.dry_run_response(
                "delete_vm_firewall_rule", vmid=vmid, pos=pos
            )
        api_path = (
            client.api.nodes(node).qemu(vmid)
            if vm_type == "qemu"
            else client.api.nodes(node).lxc(vmid)
        )
        logger.warning(
            "Deleting firewall rule %d on %s %d", pos, vm_type, vmid
        )
        await client.api_call(api_path.firewall.rules(pos).delete)
        return {"status": "success", "vmid": vmid, "node": node, "deleted_pos": pos}
    except Exception as e:
        return format_error_response(e)
