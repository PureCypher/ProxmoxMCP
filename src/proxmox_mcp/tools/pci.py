"""PCI passthrough and cluster hardware mapping tools for Proxmox VE."""

import logging
from typing import TYPE_CHECKING, Any, cast

from proxmox_mcp.utils.errors import InvalidParameterError, format_error_response
from proxmox_mcp.utils.sanitizers import (
    validate_pci_mapping_id,
    validate_pci_path,
    validate_pci_slot,
)
from proxmox_mcp.utils.validators import validate_node_name, validate_vmid

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


def _build_map_entry(node: str, path: str, device: dict) -> str:
    """Build a /cluster/mapping/pci map property-string from a device listing entry."""
    parts = [f"node={node}", f"path={path}"]
    vendor = device.get("vendor", "")
    dev_id = device.get("device", "")
    if vendor and dev_id:
        parts.append(f"id={vendor.removeprefix('0x')}:{dev_id.removeprefix('0x')}")
    iommu_group = device.get("iommugroup")
    if iommu_group is not None:
        parts.append(f"iommu-group={iommu_group}")
    subsystem_vendor = device.get("subsystem_vendor")
    subsystem_device = device.get("subsystem_device")
    if subsystem_vendor and subsystem_device:
        parts.append(
            f"subsystem-id={subsystem_vendor.removeprefix('0x')}:"
            f"{subsystem_device.removeprefix('0x')}"
        )
    return ",".join(parts)


async def _lookup_pci_device(client: "ProxmoxClient", node: str, path: str) -> dict[str, Any]:
    """Find a PCI device on `node` whose bus address matches `path`."""
    devices = await client.api_call(client.api.nodes(node).hardware.pci.get)
    normalized = path if path.count(":") == 2 else f"0000:{path}"
    for device in devices:
        dev_id = device.get("id", "")
        if dev_id == path or dev_id == normalized or dev_id.endswith(path):
            return cast(dict[str, Any], device)
    raise InvalidParameterError(
        f"No PCI device found at path '{path}' on node '{node}'. "
        f"Use list_node_pci_devices to see available devices."
    )


@mcp.tool()
async def create_pci_mapping(
    mapping_id: str,
    node: str,
    path: str,
    comment: str | None = None,
    confirm: bool = False,
) -> dict:
    """Create a cluster-wide PCI hardware mapping from one node's device.

    Set confirm=True to execute.

    Args:
        mapping_id: Name for the mapping (e.g. 'gpu0'). Used in
            assign_pci_device to attach this device to a VM.
        node: The node where the physical device currently lives.
        path: PCI bus address of the device (e.g. '01:00.0' or '0000:01:00.0').
            Use list_node_pci_devices to find it.
        comment: Optional description.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_pci_mapping_id(mapping_id)
        validate_node_name(node)
        client.validate_node(node)
        validate_pci_path(path)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will create PCI hardware mapping '{mapping_id}' "
                    f"pointing at '{path}' on node '{node}'."
                ),
                "action": "Call create_pci_mapping with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response(
                "create_pci_mapping", mapping_id=mapping_id, node=node, path=path
            )
        device = await _lookup_pci_device(client, node, path)
        map_entry = _build_map_entry(node, path, device)
        kwargs: dict = {"id": mapping_id, "map": [map_entry]}
        if comment:
            kwargs["comment"] = comment
        logger.info("Creating PCI mapping '%s' -> %s on node '%s'", mapping_id, path, node)
        await client.api_call(client.api.cluster.mapping.pci.post, **kwargs)
        return {
            "status": "success",
            "mapping_id": mapping_id,
            "node": node,
            "path": path,
            "map_entry": map_entry,
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def add_pci_mapping_target(
    mapping_id: str,
    node: str,
    path: str,
    confirm: bool = False,
) -> dict:
    """Add another node's matching device to an existing PCI mapping.

    This is what makes a mapping resolve correctly regardless of which node
    a VM lands on. Set confirm=True to execute.

    Args:
        mapping_id: Name of the existing mapping to extend.
        node: The additional node where a matching device lives.
        path: PCI bus address of the device on that node.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_pci_mapping_id(mapping_id)
        validate_node_name(node)
        client.validate_node(node)
        validate_pci_path(path)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will add node '{node}' path '{path}' as a target "
                    f"of PCI mapping '{mapping_id}'."
                ),
                "action": "Call add_pci_mapping_target with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response(
                "add_pci_mapping_target", mapping_id=mapping_id, node=node, path=path
            )
        existing = await client.api_call(client.api.cluster.mapping.pci(mapping_id).get)
        device = await _lookup_pci_device(client, node, path)
        map_entry = _build_map_entry(node, path, device)
        current_map = list(existing.get("map", []))
        current_map.append(map_entry)
        await client.api_call(client.api.cluster.mapping.pci(mapping_id).put, map=current_map)
        logger.info("Added node '%s' path '%s' to PCI mapping '%s'", node, path, mapping_id)
        return {
            "status": "success",
            "mapping_id": mapping_id,
            "node": node,
            "path": path,
            "map_entry": map_entry,
            "total_targets": len(current_map),
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_pci_mapping(mapping_id: str, confirm: bool = False) -> dict:
    """Delete a cluster-wide PCI hardware mapping. Set confirm=True to execute.

    Args:
        mapping_id: Name of the mapping to delete.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_pci_mapping_id(mapping_id)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete PCI hardware mapping '{mapping_id}'.",
                "action": "Call delete_pci_mapping with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_pci_mapping", mapping_id=mapping_id)
        logger.warning("Deleting PCI mapping '%s'", mapping_id)
        await client.api_call(client.api.cluster.mapping.pci(mapping_id).delete)
        return {"status": "success", "mapping_id": mapping_id, "deleted": True}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def assign_pci_device(
    vmid: int,
    slot: int,
    mapping_id: str,
    node: str | None = None,
    pcie: bool = True,
    rombar: bool = True,
    x_vga: bool = False,
    confirm: bool = False,
) -> dict:
    """Attach a PCI hardware mapping to a VM's hostpci slot. Set confirm=True to execute.

    Args:
        vmid: The VM ID.
        slot: hostpci slot number (0-15).
        mapping_id: Name of an existing PCI hardware mapping (see list_pci_mappings).
        node: The node name. Auto-detected if omitted.
        pcie: Present as a PCIe device (default True; required for most modern GPUs).
        rombar: Enable the device's ROM BAR (default True).
        x_vga: Mark as the VM's primary VGA device (default False).
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_pci_slot(slot)
        validate_pci_mapping_id(mapping_id)
        client.check_protected(vmid)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will attach PCI mapping '{mapping_id}' to VM {vmid} "
                    f"as hostpci{slot}."
                ),
                "action": "Call assign_pci_device with confirm=True to proceed.",
            }
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response(
                "assign_pci_device", vmid=vmid, slot=slot, mapping_id=mapping_id
            )
        value = (
            f"mapping={mapping_id},pcie={1 if pcie else 0},"
            f"rombar={1 if rombar else 0},x-vga={1 if x_vga else 0}"
        )
        kwargs = {f"hostpci{slot}": value}
        logger.info(
            "Assigning PCI mapping '%s' to VM %d as hostpci%d", mapping_id, vmid, slot
        )
        await client.api_call(client.api.nodes(node).qemu(vmid).config.put, **kwargs)
        return {
            "status": "success",
            "vmid": vmid,
            "node": node,
            "slot": slot,
            "mapping_id": mapping_id,
            "config_value": value,
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def remove_pci_device(
    vmid: int,
    slot: int,
    node: str | None = None,
    confirm: bool = False,
) -> dict:
    """Detach a PCI device from a VM's hostpci slot. Set confirm=True to execute.

    Args:
        vmid: The VM ID.
        slot: hostpci slot number (0-15) to clear.
        node: The node name. Auto-detected if omitted.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_pci_slot(slot)
        client.check_protected(vmid)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will remove hostpci{slot} from VM {vmid}.",
                "action": "Call remove_pci_device with confirm=True to proceed.",
            }
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("remove_pci_device", vmid=vmid, slot=slot)
        logger.warning("Removing hostpci%d from VM %d", slot, vmid)
        await client.api_call(
            client.api.nodes(node).qemu(vmid).config.put, delete=f"hostpci{slot}"
        )
        return {"status": "success", "vmid": vmid, "node": node, "slot": slot}
    except Exception as e:
        return format_error_response(e)
