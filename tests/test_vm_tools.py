"""Tests for VM tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.vm.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.config.PROXMOX_DRY_RUN = False
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        client.resolve_node = AsyncMock(return_value="pve1")
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
    mock_client.resolve_node.assert_called_once_with(100, None)


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


@pytest.mark.asyncio
async def test_modify_vm_config_blocks_hookscript(mock_client):
    from proxmox_mcp.tools.vm import modify_vm_config

    result = await modify_vm_config(
        vmid=100, extra_config='{"hookscript": "local:snippets/evil.sh"}'
    )
    assert result["status"] == "error"
    assert "hookscript" in result["message"]


@pytest.mark.asyncio
async def test_modify_vm_config_blocks_hostpci(mock_client):
    from proxmox_mcp.tools.vm import modify_vm_config

    result = await modify_vm_config(vmid=100, extra_config='{"hostpci0": "01:00.0"}')
    assert result["status"] == "error"
    assert "hostpci0" in result["message"]


@pytest.mark.asyncio
async def test_modify_vm_config_allows_safe_keys(mock_client):
    from proxmox_mcp.tools.vm import modify_vm_config

    mock_client.api_call = AsyncMock(return_value=None)
    result = await modify_vm_config(
        vmid=100, extra_config='{"memory": 8192, "cores": 4, "agent": "1"}'
    )
    assert result["status"] == "success"
    assert "memory" in result["changes"]
    assert "cores" in result["changes"]


@pytest.mark.asyncio
async def test_modify_vm_config_blocks_unknown_key(mock_client):
    from proxmox_mcp.tools.vm import modify_vm_config

    result = await modify_vm_config(vmid=100, extra_config='{"some_unknown_key": "value"}')
    assert result["status"] == "error"
    assert "some_unknown_key" in result["message"]


@pytest.mark.asyncio
async def test_resize_vm_disk(mock_client):
    from proxmox_mcp.tools.vm import resize_vm_disk

    mock_client.api_call = AsyncMock(return_value=None)
    result = await resize_vm_disk(vmid=100, disk="scsi0", size="+10G")
    assert result["status"] == "success"
    assert result["disk"] == "scsi0"
    assert result["size"] == "+10G"


@pytest.mark.asyncio
async def test_resize_vm_disk_protected(mock_client):
    from proxmox_mcp.tools.vm import resize_vm_disk
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await resize_vm_disk(vmid=100, disk="scsi0", size="+10G")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_resize_vm_disk_dry_run(mock_client):
    from proxmox_mcp.tools.vm import resize_vm_disk

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await resize_vm_disk(vmid=100, disk="scsi0", size="+10G")
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_convert_vm_to_template_requires_confirm(mock_client):
    from proxmox_mcp.tools.vm import convert_vm_to_template

    result = await convert_vm_to_template(vmid=100)
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_convert_vm_to_template_confirmed(mock_client):
    from proxmox_mcp.tools.vm import convert_vm_to_template

    mock_client.api_call = AsyncMock(return_value=None)
    result = await convert_vm_to_template(vmid=100, confirm=True)
    assert result["status"] == "success"
    assert "template" in result["message"]


@pytest.mark.asyncio
async def test_convert_vm_to_template_protected(mock_client):
    from proxmox_mcp.tools.vm import convert_vm_to_template
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await convert_vm_to_template(vmid=100, confirm=True)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_start_vm_protected(mock_client):
    from proxmox_mcp.tools.vm import start_vm
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await start_vm(vmid=100)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_set_vm_cloudinit(mock_client):
    from proxmox_mcp.tools.vm import set_vm_cloudinit

    mock_client.api_call = AsyncMock(return_value=None)
    result = await set_vm_cloudinit(vmid=100, ciuser="admin", ipconfig0="ip=dhcp")
    assert result["status"] == "success"
    assert "ciuser" in result["changes"]
    assert "ipconfig0" in result["changes"]


@pytest.mark.asyncio
async def test_set_vm_cloudinit_no_changes(mock_client):
    from proxmox_mcp.tools.vm import set_vm_cloudinit

    result = await set_vm_cloudinit(vmid=100)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_set_vm_cloudinit_dry_run(mock_client):
    from proxmox_mcp.tools.vm import set_vm_cloudinit

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await set_vm_cloudinit(vmid=100, ciuser="admin")
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_regenerate_cloudinit_image(mock_client):
    from proxmox_mcp.tools.vm import regenerate_cloudinit_image

    mock_client.api_call = AsyncMock(return_value=None)
    result = await regenerate_cloudinit_image(vmid=100)
    assert result["status"] == "success"
    assert "regenerated" in result["message"]


@pytest.mark.asyncio
async def test_regenerate_cloudinit_image_protected(mock_client):
    from proxmox_mcp.tools.vm import regenerate_cloudinit_image
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await regenerate_cloudinit_image(vmid=100)
    assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Regression tests (phase 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_vm_timeout_forwarded(mock_client):
    from proxmox_mcp.tools.vm import start_vm

    mock_client.api_call = AsyncMock(return_value="UPID:x")
    result = await start_vm(vmid=100, timeout=45)
    assert result["status"] == "submitted"
    _, kwargs = mock_client.api_call.call_args
    assert kwargs.get("timeout") == 45


@pytest.mark.asyncio
async def test_shutdown_vm_no_dead_timeout_kwarg(mock_client):
    from proxmox_mcp.tools.vm import shutdown_vm

    mock_client.api_call = AsyncMock(return_value="UPID:x")
    result = await shutdown_vm(vmid=100)
    assert result["status"] == "submitted"
    _, kwargs = mock_client.api_call.call_args
    assert "timeout" not in kwargs


@pytest.mark.asyncio
async def test_modify_vm_config_int_kwargs(mock_client):
    from proxmox_mcp.tools.vm import modify_vm_config

    mock_client.api_call = AsyncMock(return_value=None)
    result = await modify_vm_config(vmid=100, memory="8192", cores="4", sockets="2", balloon="2048")
    assert result["status"] == "success"
    kwargs = mock_client.api_call.call_args.kwargs
    assert kwargs["memory"] == 8192 and isinstance(kwargs["memory"], int)
    assert kwargs["cores"] == 4 and isinstance(kwargs["cores"], int)
    assert kwargs["sockets"] == 2 and isinstance(kwargs["sockets"], int)
    assert kwargs["balloon"] == 2048 and isinstance(kwargs["balloon"], int)


@pytest.mark.asyncio
async def test_modify_vm_config_long_value_rejected(mock_client):
    from proxmox_mcp.tools.vm import modify_vm_config

    mock_client.api_call = AsyncMock(return_value=None)
    result = await modify_vm_config(vmid=100, extra_config='{"tags": "%s"}' % ("a" * 4097))
    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"
    mock_client.api_call.assert_not_called()


@pytest.mark.asyncio
async def test_list_vms_invalid_status_filter(mock_client):
    from proxmox_mcp.tools.vm import list_vms

    mock_client.api_call = AsyncMock(return_value=[])
    result = await list_vms(status_filter="bogus")
    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"
    mock_client.api_call.assert_not_called()


@pytest.mark.asyncio
async def test_get_vm_rrd_data_invalid_timeframe(mock_client):
    from proxmox_mcp.tools.vm import get_vm_rrd_data

    mock_client.api_call = AsyncMock(return_value=[])
    result = await get_vm_rrd_data(vmid=100, timeframe="fortnight")
    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"
    mock_client.api_call.assert_not_called()


@pytest.mark.asyncio
async def test_list_vms_empty_not_silent(mock_client):
    """Unknown status_filter must error, and a valid filter on empty result succeeds."""
    from proxmox_mcp.tools.vm import list_vms

    mock_client.api_call = AsyncMock(return_value=[])
    result = await list_vms(status_filter="paused")
    assert result["status"] == "success"
    assert result["total"] == 0
    result = await list_vms(status_filter="nonexistent")
    assert result["status"] == "error"
    assert "bogus" not in result.get("message", "")
    assert "nonexistent" in result["message"]
