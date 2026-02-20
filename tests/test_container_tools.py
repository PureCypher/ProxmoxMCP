"""Tests for container tools."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.container.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.config.PROXMOX_DRY_RUN = False
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_list_containers(mock_client):
    from proxmox_mcp.tools.container import list_containers
    mock_client.api_call = AsyncMock(return_value=[
        {"vmid": 200, "name": "ct1", "status": "running", "node": "pve1",
         "type": "lxc", "maxcpu": 1, "maxmem": 536870912, "mem": 268435456,
         "maxdisk": 8589934592, "uptime": 3600, "cpu": 0.02},
    ])
    result = await list_containers()
    assert result["status"] == "success"
    assert result["containers"][0]["type"] == "lxc"


@pytest.mark.asyncio
async def test_get_container_status(mock_client):
    from proxmox_mcp.tools.container import get_container_status
    mock_client.api_call = AsyncMock(return_value={"status": "running", "vmid": 200})
    result = await get_container_status(vmid=200)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_start_container(mock_client):
    from proxmox_mcp.tools.container import start_container
    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00001:start")
    result = await start_container(vmid=200)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_stop_container_protected(mock_client):
    from proxmox_mcp.tools.container import stop_container
    from proxmox_mcp.utils.errors import ProtectedResourceError
    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await stop_container(vmid=200)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_delete_container_requires_confirm(mock_client):
    from proxmox_mcp.tools.container import delete_container
    mock_client.api_call = AsyncMock(
        return_value={"status": "stopped", "vmid": 200, "name": "test-ct"}
    )
    result = await delete_container(vmid=200)
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_create_container(mock_client):
    from proxmox_mcp.tools.container import create_container
    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00006:create")
    result = await create_container(
        node="pve1", ostemplate="local:vztmpl/ubuntu-22.04.tar.zst", hostname="test-ct"
    )
    assert result["status"] == "submitted"
