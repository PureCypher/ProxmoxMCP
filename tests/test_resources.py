"""Tests for MCP resource definitions."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.resources.resources.get_client") as mock_get:
        client = MagicMock()
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


# --- cluster_status ---


@pytest.mark.asyncio
async def test_cluster_status(mock_client):
    from proxmox_mcp.resources.resources import cluster_status

    mock_client.api_call = AsyncMock(return_value=[{"type": "cluster", "name": "pve"}])
    result = await cluster_status()

    data = json.loads(result)
    assert isinstance(data, list)
    assert data[0]["type"] == "cluster"


@pytest.mark.asyncio
async def test_cluster_status_error(mock_client):
    from proxmox_mcp.resources.resources import cluster_status

    mock_client.api_call = AsyncMock(side_effect=Exception("connection refused"))
    result = await cluster_status()

    data = json.loads(result)
    assert "error" in data


# --- cluster_resources ---


@pytest.mark.asyncio
async def test_cluster_resources(mock_client):
    from proxmox_mcp.resources.resources import cluster_resources

    mock_client.api_call = AsyncMock(
        return_value=[{"type": "qemu", "vmid": 100, "name": "vm1", "node": "pve1"}]
    )
    result = await cluster_resources()

    data = json.loads(result)
    assert len(data) == 1
    assert data[0]["vmid"] == 100


# --- nodes_list ---


@pytest.mark.asyncio
async def test_nodes_list(mock_client):
    from proxmox_mcp.resources.resources import nodes_list

    mock_client.api_call = AsyncMock(
        return_value=[{"node": "pve1", "status": "online", "cpu": 0.1}]
    )
    result = await nodes_list()

    data = json.loads(result)
    assert data[0]["node"] == "pve1"


# --- node_status ---


@pytest.mark.asyncio
async def test_node_status(mock_client):
    from proxmox_mcp.resources.resources import node_status

    mock_client.api_call = AsyncMock(
        return_value={"uptime": 86400, "memory": {"used": 1024, "total": 8192}}
    )
    result = await node_status(node="pve1")

    data = json.loads(result)
    assert data["uptime"] == 86400


@pytest.mark.asyncio
async def test_node_status_error(mock_client):
    from proxmox_mcp.resources.resources import node_status

    mock_client.api_call = AsyncMock(side_effect=Exception("node offline"))
    result = await node_status(node="pve1")

    data = json.loads(result)
    assert "error" in data


# --- all_vms ---


@pytest.mark.asyncio
async def test_all_vms(mock_client):
    from proxmox_mcp.resources.resources import all_vms

    mock_client.api_call = AsyncMock(
        return_value=[
            {
                "type": "qemu",
                "vmid": 100,
                "name": "vm1",
                "status": "running",
                "node": "pve1",
                "maxcpu": 2,
                "maxmem": 2147483648,
                "mem": 1073741824,
                "maxdisk": 10737418240,
                "uptime": 3600,
                "cpu": 0.05,
            },
            {
                "type": "lxc",
                "vmid": 200,
                "name": "ct1",
                "status": "running",
                "node": "pve1",
                "maxcpu": 1,
                "maxmem": 536870912,
                "mem": 268435456,
                "maxdisk": 4294967296,
                "uptime": 7200,
                "cpu": 0.02,
            },
        ]
    )
    result = await all_vms()

    data = json.loads(result)
    # Should only include QEMU VMs, not LXC
    assert len(data) == 1
    assert data[0]["vmid"] == 100
    assert data[0]["type"] == "qemu"


# --- all_containers ---


@pytest.mark.asyncio
async def test_all_containers(mock_client):
    from proxmox_mcp.resources.resources import all_containers

    mock_client.api_call = AsyncMock(
        return_value=[
            {
                "type": "qemu",
                "vmid": 100,
                "name": "vm1",
                "status": "running",
                "node": "pve1",
                "maxcpu": 2,
                "maxmem": 2147483648,
                "mem": 1073741824,
                "maxdisk": 10737418240,
                "uptime": 3600,
                "cpu": 0.05,
            },
            {
                "type": "lxc",
                "vmid": 200,
                "name": "ct1",
                "status": "running",
                "node": "pve1",
                "maxcpu": 1,
                "maxmem": 536870912,
                "mem": 268435456,
                "maxdisk": 4294967296,
                "uptime": 7200,
                "cpu": 0.02,
            },
        ]
    )
    result = await all_containers()

    data = json.loads(result)
    # Should only include LXC containers, not QEMU
    assert len(data) == 1
    assert data[0]["vmid"] == 200
    assert data[0]["type"] == "lxc"


# --- vm_detail ---


@pytest.mark.asyncio
async def test_vm_detail(mock_client):
    from proxmox_mcp.resources.resources import vm_detail

    mock_client.api_call = AsyncMock(
        side_effect=[
            {"status": "running", "vmid": 100},  # status.current.get
            {"name": "test-vm", "memory": 2048},  # config.get
        ]
    )
    result = await vm_detail(vmid=100)

    data = json.loads(result)
    assert data["status"]["vmid"] == 100
    assert data["config"]["name"] == "test-vm"
    assert data["node"] == "pve1"


@pytest.mark.asyncio
async def test_vm_detail_not_found(mock_client):
    from proxmox_mcp.resources.resources import vm_detail

    mock_client.resolve_node_for_vmid = AsyncMock(side_effect=Exception("VMID 999 not found"))
    result = await vm_detail(vmid=999)

    data = json.loads(result)
    assert "error" in data


# --- container_detail ---


@pytest.mark.asyncio
async def test_container_detail(mock_client):
    from proxmox_mcp.resources.resources import container_detail

    mock_client.api_call = AsyncMock(
        side_effect=[
            {"status": "running", "vmid": 200},  # status.current.get
            {"hostname": "ct1", "memory": 512},  # config.get
        ]
    )
    result = await container_detail(vmid=200)

    data = json.loads(result)
    assert data["status"]["vmid"] == 200
    assert data["config"]["hostname"] == "ct1"


# --- storage_overview ---


@pytest.mark.asyncio
async def test_storage_overview(mock_client):
    from proxmox_mcp.resources.resources import storage_overview

    mock_client.api_call = AsyncMock(
        return_value=[
            {"storage": "local", "type": "dir", "content": "images,iso"},
            {"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir"},
        ]
    )
    result = await storage_overview()

    data = json.loads(result)
    assert len(data) == 2
    assert data[0]["storage"] == "local"


# --- recent_tasks ---


@pytest.mark.asyncio
async def test_recent_tasks(mock_client):
    from proxmox_mcp.resources.resources import recent_tasks

    mock_client.api_call = AsyncMock(
        side_effect=[
            [{"node": "pve1"}],  # nodes.get
            [  # tasks.get for pve1
                {"upid": "UPID:pve1:001", "status": "ok", "starttime": 1000},
                {"upid": "UPID:pve1:002", "status": "running", "starttime": 2000},
            ],
        ]
    )
    result = await recent_tasks()

    data = json.loads(result)
    assert len(data) == 2
    # Should be sorted by starttime descending
    assert data[0]["starttime"] == 2000


@pytest.mark.asyncio
async def test_recent_tasks_error(mock_client):
    from proxmox_mcp.resources.resources import recent_tasks

    mock_client.api_call = AsyncMock(side_effect=Exception("cluster error"))
    result = await recent_tasks()

    data = json.loads(result)
    assert "error" in data
