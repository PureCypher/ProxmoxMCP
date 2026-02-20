"""Tests for cluster tools."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_client():
    """Create a mock ProxmoxClient with api_call as AsyncMock."""
    client = MagicMock()
    client.api_call = AsyncMock()
    return client


# --- get_cluster_status ---

@pytest.mark.asyncio
async def test_get_cluster_status(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_status

    mock_client.api_call.return_value = [
        {
            "type": "cluster",
            "name": "testcluster",
            "version": 3,
            "quorate": 1,
            "nodes": 2,
        },
        {
            "type": "node",
            "name": "pve1",
            "id": "node/pve1",
            "online": 1,
            "ip": "10.0.0.1",
            "level": "",
            "local": 1,
        },
        {
            "type": "node",
            "name": "pve2",
            "id": "node/pve2",
            "online": 1,
            "ip": "10.0.0.2",
            "level": "",
            "local": 0,
        },
    ]

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_status()

    assert result["status"] == "success"
    assert result["cluster"]["name"] == "testcluster"
    assert result["cluster"]["quorate"] == 1
    assert len(result["nodes"]) == 2
    assert result["nodes"][0]["name"] == "pve1"
    assert result["nodes"][1]["name"] == "pve2"


@pytest.mark.asyncio
async def test_get_cluster_status_error(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_status

    mock_client.api_call.side_effect = Exception("Connection refused")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_status()

    assert result["status"] == "error"
    assert "Connection refused" in result["message"]


# --- get_cluster_resources ---

@pytest.mark.asyncio
async def test_get_cluster_resources_all(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_resources

    mock_client.api_call.return_value = [
        {"type": "qemu", "vmid": 100, "node": "pve1"},
        {"type": "storage", "storage": "local", "node": "pve1"},
    ]

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_resources()

    assert result["status"] == "success"
    assert result["resource_type"] == "all"
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_get_cluster_resources_filtered(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_resources

    mock_client.api_call.return_value = [
        {"type": "qemu", "vmid": 100, "node": "pve1"},
    ]

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_resources(resource_type="vm")

    assert result["status"] == "success"
    assert result["resource_type"] == "vm"
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_get_cluster_resources_error(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_resources

    mock_client.api_call.side_effect = Exception("API error")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_resources()

    assert result["status"] == "error"


# --- get_cluster_log ---

@pytest.mark.asyncio
async def test_get_cluster_log(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_log

    mock_client.api_call.return_value = [
        {"tag": "pvedaemon", "msg": "starting server", "time": 1700000000},
        {"tag": "pvedaemon", "msg": "ready", "time": 1700000001},
    ]

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_log(max_entries=10)

    assert result["status"] == "success"
    assert result["count"] == 2
    assert len(result["entries"]) == 2


@pytest.mark.asyncio
async def test_get_cluster_log_error(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_log

    mock_client.api_call.side_effect = Exception("timeout")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_log()

    assert result["status"] == "error"


# --- get_next_vmid ---

@pytest.mark.asyncio
async def test_get_next_vmid(mock_client):
    from proxmox_mcp.tools.cluster import get_next_vmid

    mock_client.api_call.return_value = "105"

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_next_vmid()

    assert result["status"] == "success"
    assert result["vmid"] == 105
    assert isinstance(result["vmid"], int)


@pytest.mark.asyncio
async def test_get_next_vmid_error(mock_client):
    from proxmox_mcp.tools.cluster import get_next_vmid

    mock_client.api_call.side_effect = Exception("cluster error")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_next_vmid()

    assert result["status"] == "error"


# --- list_pools ---

@pytest.mark.asyncio
async def test_list_pools(mock_client):
    from proxmox_mcp.tools.cluster import list_pools

    mock_client.api_call.return_value = [
        {"poolid": "production", "comment": "Production VMs"},
        {"poolid": "testing", "comment": "Test environment"},
    ]

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await list_pools()

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["pools"][0]["poolid"] == "production"


@pytest.mark.asyncio
async def test_list_pools_empty(mock_client):
    from proxmox_mcp.tools.cluster import list_pools

    mock_client.api_call.return_value = []

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await list_pools()

    assert result["status"] == "success"
    assert result["count"] == 0
    assert result["pools"] == []


@pytest.mark.asyncio
async def test_list_pools_error(mock_client):
    from proxmox_mcp.tools.cluster import list_pools

    mock_client.api_call.side_effect = Exception("permission denied")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await list_pools()

    assert result["status"] == "error"
