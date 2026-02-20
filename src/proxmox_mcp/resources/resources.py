# src/proxmox_mcp/resources/resources.py
"""MCP resource definitions exposing Proxmox state."""

import json
import logging
from proxmox_mcp.utils.formatters import format_vm_summary, format_container_summary

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.resource("proxmox://cluster/status")
async def cluster_status() -> str:
    """Current cluster health, quorum, and node membership."""
    client = get_client()
    data = await client.api_call(client.api.cluster.status.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://cluster/resources")
async def cluster_resources() -> str:
    """All resources (VMs, CTs, nodes, storage) in the cluster."""
    client = get_client()
    data = await client.api_call(client.api.cluster.resources.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://nodes")
async def nodes_list() -> str:
    """All nodes with CPU, memory, and status summary."""
    client = get_client()
    data = await client.api_call(client.api.nodes.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://node/{node}/status")
async def node_status(node: str) -> str:
    """Detailed status for a specific node."""
    client = get_client()
    data = await client.api_call(client.api.nodes(node).status.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://vms")
async def all_vms() -> str:
    """All QEMU VMs across the cluster with status."""
    client = get_client()
    resources = await client.api_call(client.api.cluster.resources.get, type="vm")
    vms = [format_vm_summary(r) for r in resources if r.get("type") == "qemu"]
    return json.dumps(vms, indent=2, default=str)


@mcp.resource("proxmox://containers")
async def all_containers() -> str:
    """All LXC containers across the cluster with status."""
    client = get_client()
    resources = await client.api_call(client.api.cluster.resources.get, type="vm")
    cts = [format_container_summary(r) for r in resources if r.get("type") == "lxc"]
    return json.dumps(cts, indent=2, default=str)


@mcp.resource("proxmox://vm/{vmid}")
async def vm_detail(vmid: int) -> str:
    """Detailed info for a specific VM (config + status)."""
    client = get_client()
    node = await client.resolve_node_for_vmid(vmid)
    status = await client.api_call(client.api.nodes(node).qemu(vmid).status.current.get)
    config = await client.api_call(client.api.nodes(node).qemu(vmid).config.get)
    return json.dumps({"status": status, "config": config, "node": node}, indent=2, default=str)


@mcp.resource("proxmox://container/{vmid}")
async def container_detail(vmid: int) -> str:
    """Detailed info for a specific container (config + status)."""
    client = get_client()
    node = await client.resolve_node_for_vmid(vmid)
    status = await client.api_call(client.api.nodes(node).lxc(vmid).status.current.get)
    config = await client.api_call(client.api.nodes(node).lxc(vmid).config.get)
    return json.dumps({"status": status, "config": config, "node": node}, indent=2, default=str)


@mcp.resource("proxmox://storage")
async def storage_overview() -> str:
    """All storage pools with usage percentages."""
    client = get_client()
    data = await client.api_call(client.api.storage.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://tasks/recent")
async def recent_tasks() -> str:
    """Last 20 tasks with status and timing."""
    client = get_client()
    nodes = await client.api_call(client.api.nodes.get)
    all_tasks = []
    for n in nodes:
        tasks = await client.api_call(client.api.nodes(n["node"]).tasks.get, limit=20)
        all_tasks.extend(tasks)
    all_tasks.sort(key=lambda t: t.get("starttime", 0), reverse=True)
    return json.dumps(all_tasks[:20], indent=2, default=str)
