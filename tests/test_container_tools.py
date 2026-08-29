"""Tests for container tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.container.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.config.PROXMOX_DRY_RUN = False
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        client.resolve_node = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


async def test_list_containers(mock_client):
    from proxmox_mcp.tools.container import list_containers

    mock_client.api_call = AsyncMock(
        return_value=[
            {
                "vmid": 200,
                "name": "ct1",
                "status": "running",
                "node": "pve1",
                "type": "lxc",
                "maxcpu": 1,
                "maxmem": 536870912,
                "mem": 268435456,
                "maxdisk": 8589934592,
                "uptime": 3600,
                "cpu": 0.02,
            },
        ]
    )
    result = await list_containers()
    assert result["status"] == "success"
    assert result["containers"][0]["type"] == "lxc"


async def test_get_container_status(mock_client):
    from proxmox_mcp.tools.container import get_container_status

    mock_client.api_call = AsyncMock(return_value={"status": "running", "vmid": 200})
    result = await get_container_status(vmid=200)
    assert result["status"] == "success"


async def test_start_container(mock_client):
    from proxmox_mcp.tools.container import start_container

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00001:start")
    result = await start_container(vmid=200)
    assert result["status"] == "submitted"


async def test_stop_container_protected(mock_client):
    from proxmox_mcp.tools.container import stop_container
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await stop_container(vmid=200)
    assert result["status"] == "error"


async def test_delete_container_requires_confirm(mock_client):
    from proxmox_mcp.tools.container import delete_container

    mock_client.api_call = AsyncMock(
        return_value={"status": "stopped", "vmid": 200, "name": "test-ct"}
    )
    result = await delete_container(vmid=200)
    assert result["status"] == "confirmation_required"


async def test_create_container(mock_client):
    from proxmox_mcp.tools.container import create_container

    mock_client.api_call = AsyncMock(return_value="UPID:pve1:00006:create")
    result = await create_container(
        node="pve1", ostemplate="local:vztmpl/ubuntu-22.04.tar.zst", hostname="test-ct"
    )
    assert result["status"] == "submitted"


async def test_modify_container_config_blocks_hookscript(mock_client):
    from proxmox_mcp.tools.container import modify_container_config

    result = await modify_container_config(
        vmid=200, extra_config='{"hookscript": "local:snippets/evil.sh"}'
    )
    assert result["status"] == "error"
    assert "hookscript" in result["message"]


async def test_modify_container_config_allows_safe_keys(mock_client):
    from proxmox_mcp.tools.container import modify_container_config

    mock_client.api_call = AsyncMock(return_value=None)
    result = await modify_container_config(vmid=200, extra_config='{"memory": 1024, "cores": 2}')
    assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Regression tests (phase 3)
# ---------------------------------------------------------------------------


async def test_start_container_protected(mock_client):
    from proxmox_mcp.tools.container import start_container

    with patch("proxmox_mcp.tools.container.get_client") as mock_get:
        c = MagicMock()
        c.is_dry_run = False
        c.resolve_node = AsyncMock(return_value="pve1")
        c.check_protected.side_effect = Exception("protected")
        mock_get.return_value = c
        result = await start_container(vmid=999)
    assert result["status"] == "error"
    c.check_protected.assert_called_once_with(999)


async def test_start_container_protected_blocks(mock_client):
    from proxmox_mcp.tools.container import start_container

    mock_client.check_protected = MagicMock(side_effect=Exception("protected"))
    result = await start_container(vmid=999)
    assert result["status"] == "error"
    mock_client.api_call.assert_not_called()


async def test_shutdown_container_no_dead_timeout_kwarg(mock_client):
    from proxmox_mcp.tools.container import shutdown_container

    mock_client.api_call = AsyncMock(return_value="UPID:x")
    result = await shutdown_container(vmid=200)
    assert result["status"] == "submitted"
    _, kwargs = mock_client.api_call.call_args
    assert "timeout" not in kwargs


async def test_create_container_rootfs_size_int(mock_client):
    from proxmox_mcp.tools.container import create_container

    mock_client.api_call = AsyncMock(return_value="UPID:x")
    result = await create_container(node="pve1", ostemplate="local:vztmpl/x.tar.zst", hostname="h")
    assert result["status"] == "submitted"
    kwargs = mock_client.api_call.call_args.kwargs
    assert kwargs["rootfs"] == "local-lvm:8"
    assert isinstance(kwargs["cores"], int)
