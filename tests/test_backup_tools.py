"""Tests for backup and snapshot tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.backup.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        client.resolve_node = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


async def test_create_snapshot(mock_client):
    from proxmox_mcp.tools.backup import create_snapshot

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:snap")
    result = await create_snapshot(vmid=100, snapname="before-upgrade")
    assert result["status"] == "submitted"


async def test_list_snapshots(mock_client):
    from proxmox_mcp.tools.backup import list_snapshots

    mock_client.api_call = AsyncMock(
        return_value=[
            {"name": "snap1", "description": "test", "snaptime": 1700000000},
        ]
    )
    result = await list_snapshots(vmid=100)
    assert result["status"] == "success"


async def test_rollback_snapshot_requires_confirm(mock_client):
    from proxmox_mcp.tools.backup import rollback_snapshot

    result = await rollback_snapshot(vmid=100, snapname="snap1")
    assert result["status"] == "confirmation_required"


async def test_create_backup(mock_client):
    from proxmox_mcp.tools.backup import create_backup

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:vzdump")
    result = await create_backup(vmid=100)
    assert result["status"] == "submitted"


async def test_list_backups(mock_client):
    from proxmox_mcp.tools.backup import list_backups

    mock_client.api_call = AsyncMock(
        return_value=[
            {"volid": "local:backup/vm-100.vma.zst", "size": 1073741824},
        ]
    )
    result = await list_backups(node="pve1")
    assert result["status"] == "success"


# --- list_backup_jobs ---


async def test_list_backup_jobs(mock_client):
    from proxmox_mcp.tools.backup import list_backup_jobs

    mock_client.api_call = AsyncMock(
        return_value=[
            {"id": "backup-001", "schedule": "0 2 * * *", "storage": "local"},
        ]
    )
    result = await list_backup_jobs()
    assert result["status"] == "success"
    assert result["count"] == 1


# --- create_backup_job ---


async def test_create_backup_job(mock_client):
    from proxmox_mcp.tools.backup import create_backup_job

    mock_client.api_call = AsyncMock(return_value=None)
    result = await create_backup_job(storage="local", schedule="daily", vmid="100,101")
    assert result["status"] == "success"
    assert result["schedule"] == "daily"


async def test_create_backup_job_dry_run(mock_client):
    from proxmox_mcp.tools.backup import create_backup_job

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await create_backup_job(storage="local", schedule="at 03:00")
    assert result["status"] == "dry_run"


# --- delete_backup_job ---


async def test_delete_backup_job_requires_confirm(mock_client):
    from proxmox_mcp.tools.backup import delete_backup_job

    result = await delete_backup_job(job_id="backup-001")
    assert result["status"] == "confirmation_required"


async def test_delete_backup_job_confirmed(mock_client):
    from proxmox_mcp.tools.backup import delete_backup_job

    mock_client.api_call = AsyncMock(return_value=None)
    result = await delete_backup_job(job_id="backup-001", confirm=True)
    assert result["status"] == "success"
    assert result["job_id"] == "backup-001"


# ---------------------------------------------------------------------------
# Regression tests (phase 3)
# ---------------------------------------------------------------------------


async def test_create_backup_job_invalid_cron_schedule(mock_client):
    from proxmox_mcp.tools.backup import create_backup_job

    mock_client.api_call = AsyncMock(return_value=None)
    result = await create_backup_job(storage="local", schedule="0 2 * * *")
    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"
    mock_client.api_call.assert_not_called()


async def test_create_backup_job_valid_schedules(mock_client):
    from proxmox_mcp.tools.backup import create_backup_job

    mock_client.api_call = AsyncMock(return_value=None)
    for sched in ("daily", "weekly", "monthly", "hourly", "at 02:00"):
        mock_client.api_call.reset_mock()
        result = await create_backup_job(storage="local", schedule=sched)
        assert result["status"] == "success", sched


async def test_create_backup_job_bad_at_time(mock_client):
    from proxmox_mcp.tools.backup import create_backup_job

    mock_client.api_call = AsyncMock(return_value=None)
    for bad in ("at 24:00", "at 00:60", "at 2:5", "atnoon"):
        mock_client.api_call.reset_mock()
        result = await create_backup_job(storage="local", schedule=bad)
        assert result["status"] == "error", bad
    assert mock_client.api_call.call_count == 0
