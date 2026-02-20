"""Tests for backup and snapshot tools."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.backup.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_create_snapshot(mock_client):
    from proxmox_mcp.tools.backup import create_snapshot
    mock_client.api_call = AsyncMock(return_value="UPID:pve1:snap")
    result = await create_snapshot(vmid=100, snapname="before-upgrade")
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_list_snapshots(mock_client):
    from proxmox_mcp.tools.backup import list_snapshots
    mock_client.api_call = AsyncMock(return_value=[
        {"name": "snap1", "description": "test", "snaptime": 1700000000},
    ])
    result = await list_snapshots(vmid=100)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_rollback_snapshot_requires_confirm(mock_client):
    from proxmox_mcp.tools.backup import rollback_snapshot
    result = await rollback_snapshot(vmid=100, snapname="snap1")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_create_backup(mock_client):
    from proxmox_mcp.tools.backup import create_backup
    mock_client.api_call = AsyncMock(return_value="UPID:pve1:vzdump")
    result = await create_backup(vmid=100)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_list_backups(mock_client):
    from proxmox_mcp.tools.backup import list_backups
    mock_client.api_call = AsyncMock(return_value=[
        {"volid": "local:backup/vm-100.vma.zst", "size": 1073741824},
    ])
    result = await list_backups(node="pve1")
    assert result["status"] == "success"
