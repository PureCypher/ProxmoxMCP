"""Tests for VM tools."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.vm.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.config.PROXMOX_DRY_RUN = False
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_list_vms(mock_client):
    from proxmox_mcp.tools.vm import list_vms

    mock_client.api_call = AsyncMock(
        return_value=[
            {
                "vmid": 100,
                "name": "vm1",
                "status": "running",
                "node": "pve1",
                "type": "qemu",
                "maxcpu": 2,
                "maxmem": 2147483648,
                "mem": 1073741824,
                "maxdisk": 34359738368,
                "uptime": 3600,
                "cpu": 0.05,
            },
        ]
    )
    result = await list_vms()
    assert result["status"] == "success"
    assert len(result["vms"]) == 1
    assert result["vms"][0]["type"] == "qemu"


@pytest.mark.asyncio
async def test_list_vms_filter_running(mock_client):
    from proxmox_mcp.tools.vm import list_vms

    mock_client.api_call = AsyncMock(
        return_value=[
            {
                "vmid": 100,
                "status": "running",
                "name": "a",
                "type": "qemu",
                "maxcpu": 1,
                "maxmem": 0,
                "mem": 0,
                "maxdisk": 0,
                "uptime": 0,
                "cpu": 0,
            },
            {
                "vmid": 101,
                "status": "stopped",
                "name": "b",
                "type": "qemu",
                "maxcpu": 1,
                "maxmem": 0,
                "mem": 0,
                "maxdisk": 0,
                "uptime": 0,
                "cpu": 0,
            },
        ]
    )
    result = await list_vms(status_filter="running")
    assert len(result["vms"]) == 1


@pytest.mark.asyncio
async def test_get_vm_status(mock_client):
    from proxmox_mcp.tools.vm import get_vm_status

    mock_client.api_call = AsyncMock(
        return_value={
            "status": "running",
            "vmid": 100,
            "name": "test",
            "qmpstatus": "running",
            "cpu": 0.1,
            "maxmem": 2147483648,
            "mem": 1073741824,
        }
    )
    result = await get_vm_status(vmid=100)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_get_vm_status_auto_detect_node(mock_client):
    from proxmox_mcp.tools.vm import get_vm_status

    mock_client.api_call = AsyncMock(return_value={"status": "running", "vmid": 100})
    await get_vm_status(vmid=100)
    mock_client.resolve_node_for_vmid.assert_called_once_with(100)


@pytest.mark.asyncio
async def test_get_vm_config(mock_client):
    from proxmox_mcp.tools.vm import get_vm_config

    mock_client.api_call = AsyncMock(
        return_value={
            "name": "test",
            "memory": 2048,
            "cores": 2,
            "sockets": 1,
        }
    )
    result = await get_vm_config(vmid=100)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_get_vm_rrd_data(mock_client):
    from proxmox_mcp.tools.vm import get_vm_rrd_data

    mock_client.api_call = AsyncMock(return_value=[{"time": 1000, "cpu": 0.1}])
    result = await get_vm_rrd_data(vmid=100, timeframe="hour")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_start_vm(mock_client):
    from proxmox_mcp.tools.vm import start_vm

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00001:start")
    result = await start_vm(vmid=100)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_stop_vm(mock_client):
    from proxmox_mcp.tools.vm import stop_vm

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00002:stop")
    result = await stop_vm(vmid=100)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_stop_vm_protected(mock_client):
    from proxmox_mcp.tools.vm import stop_vm
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await stop_vm(vmid=100)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_stop_vm_dry_run(mock_client):
    from proxmox_mcp.tools.vm import stop_vm

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {
        "status": "dry_run",
        "action": "stop_vm",
        "params": {},
        "message": "DRY RUN",
    }
    result = await stop_vm(vmid=100)
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_shutdown_vm(mock_client):
    from proxmox_mcp.tools.vm import shutdown_vm

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00003:shutdown")
    result = await shutdown_vm(vmid=100)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_delete_vm_requires_confirm(mock_client):
    from proxmox_mcp.tools.vm import delete_vm

    mock_client.api_call = AsyncMock(
        return_value={"status": "running", "vmid": 100, "name": "test"}
    )
    result = await delete_vm(vmid=100)
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_delete_vm_confirmed(mock_client):
    from proxmox_mcp.tools.vm import delete_vm

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00010:destroy")
    result = await delete_vm(vmid=100, confirm=True)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_clone_vm(mock_client):
    from proxmox_mcp.tools.vm import clone_vm

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00004:clone")
    result = await clone_vm(vmid=100, newid=200, name="clone-vm")
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_create_vm(mock_client):
    from proxmox_mcp.tools.vm import create_vm

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00005:create")
    result = await create_vm(node="pve1", name="new-vm")
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_modify_vm_config(mock_client):
    from proxmox_mcp.tools.vm import modify_vm_config

    mock_client.api_call = AsyncMock(return_value=None)
    result = await modify_vm_config(vmid=100, memory=4096, cores=4)
    assert result["status"] == "success"
