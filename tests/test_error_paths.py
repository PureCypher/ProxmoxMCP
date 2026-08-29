"""Error-path regression tests for VM/container/backup/network tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _client(module: str, api_error: Exception) -> MagicMock:
    with patch(f"{module}.get_client") as mock_get:
        client = MagicMock()
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        client.resolve_node = AsyncMock(return_value="pve1")
        client.check_protected = MagicMock()
        client.api_call = AsyncMock(side_effect=api_error)
        mock_get.return_value = client
        return client


async def _expect_error(result: dict) -> None:
    assert result["status"] == "error"
    assert "error_type" in result
    assert "message" in result


@pytest.mark.asyncio
async def test_get_vm_status_api_error():
    from proxmox_mcp.tools.vm import get_vm_status

    _client("proxmox_mcp.tools.vm", Exception("500 internal server error"))
    result = await get_vm_status(vmid=100)
    assert result["status"] == "error"
    assert "Use list_vms" in result.get("suggestion", "")


@pytest.mark.asyncio
async def test_reboot_vm_api_error():
    from proxmox_mcp.tools.vm import reboot_vm

    _client("proxmox_mcp.tools.vm", Exception("API down"))
    result = await reboot_vm(vmid=100)
    await _expect_error(result)


@pytest.mark.asyncio
async def test_suspend_resume_reset_vm_api_error():
    from proxmox_mcp.tools.vm import reset_vm, resume_vm, suspend_vm

    for tool in (suspend_vm, resume_vm, reset_vm):
        _client("proxmox_mcp.tools.vm", Exception("API down"))
        result = await tool(vmid=100)
        await _expect_error(result)


@pytest.mark.asyncio
async def test_get_container_config_api_error():
    from proxmox_mcp.tools.container import get_container_config

    _client("proxmox_mcp.tools.container", Exception("500 internal server error"))
    result = await get_container_config(vmid=200)
    await _expect_error(result)


@pytest.mark.asyncio
async def test_shutdown_container_api_error():
    from proxmox_mcp.tools.container import shutdown_container

    _client("proxmox_mcp.tools.container", Exception("API down"))
    result = await shutdown_container(vmid=200)
    await _expect_error(result)


@pytest.mark.asyncio
async def test_delete_container_api_error():
    from proxmox_mcp.tools.container import delete_container

    _client("proxmox_mcp.tools.container", Exception("API down"))
    result = await delete_container(vmid=200, confirm=True)
    await _expect_error(result)


@pytest.mark.asyncio
async def test_create_snapshot_api_error():
    from proxmox_mcp.tools.backup import create_snapshot

    _client("proxmox_mcp.tools.backup", Exception("500 snapshot failed"))
    result = await create_snapshot(vmid=100, snapname="snap1")
    await _expect_error(result)


@pytest.mark.asyncio
async def test_get_node_firewall_rules_api_error():
    from proxmox_mcp.tools.network import get_node_firewall_rules

    _client("proxmox_mcp.tools.network", Exception("403 forbidden"))
    result = await get_node_firewall_rules(node="pve1")
    await _expect_error(result)


@pytest.mark.asyncio
async def test_container_happy_paths():
    """Happy-path coverage: config, reboot, clone, migrate, delete."""
    from proxmox_mcp.tools.container import (
        clone_container,
        delete_container,
        get_container_config,
        migrate_container,
        reboot_container,
    )

    with patch("proxmox_mcp.tools.container.get_client") as mock_get:
        client = MagicMock()
        client.is_dry_run = False
        client.resolve_node = AsyncMock(return_value="pve1")
        client.check_protected = MagicMock()
        client.api_call = AsyncMock(return_value="UPID:x")
        mock_get.return_value = client

        result = await get_container_config(vmid=200)
        assert result["status"] == "success"
        assert client.api_call.call_count == 1

        result = await reboot_container(vmid=200)
        assert result["status"] == "submitted"
        client.check_protected.assert_called_with(200)

        result = await clone_container(vmid=200, newid=201, name="ct2")
        assert result["status"] == "submitted"
        kwargs = client.api_call.call_args.kwargs
        assert kwargs["newid"] == 201 and kwargs["hostname"] == "ct2"

        result = await migrate_container(vmid=200, target_node="pve2")
        assert result["status"] == "submitted"
        kwargs = client.api_call.call_args.kwargs
        assert kwargs["target"] == "pve2" and kwargs["restart"] == 1

        client.api_call = AsyncMock(return_value={"name": "ct200", "vmid": 200})
        result = await delete_container(vmid=200)
        assert result["status"] == "confirmation_required"

        client.api_call = AsyncMock(return_value="UPID:x")
        result = await delete_container(vmid=200, confirm=True)
        assert result["status"] == "submitted"
