"""Tests for network and firewall tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.network.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        client.resolve_node = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


# --- get_node_firewall_rules ---


@pytest.mark.asyncio
async def test_get_node_firewall_rules(mock_client):
    from proxmox_mcp.tools.network import get_node_firewall_rules

    rules = [
        {"pos": 0, "type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "22"},
        {"pos": 1, "type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "8006"},
    ]
    mock_client.api_call = AsyncMock(return_value=rules)
    result = await get_node_firewall_rules(node="pve1")

    assert result["status"] == "success"
    assert result["node"] == "pve1"
    assert result["total"] == 2
    assert result["rules"] == rules


@pytest.mark.asyncio
async def test_get_node_firewall_rules_empty(mock_client):
    from proxmox_mcp.tools.network import get_node_firewall_rules

    mock_client.api_call = AsyncMock(return_value=[])
    result = await get_node_firewall_rules(node="pve1")

    assert result["status"] == "success"
    assert result["total"] == 0
    assert result["rules"] == []


@pytest.mark.asyncio
async def test_get_node_firewall_rules_error(mock_client):
    from proxmox_mcp.tools.network import get_node_firewall_rules

    mock_client.api_call = AsyncMock(side_effect=Exception("API error"))
    result = await get_node_firewall_rules(node="pve1")

    assert result["status"] == "error"


# --- get_vm_firewall_rules ---


@pytest.mark.asyncio
async def test_get_vm_firewall_rules(mock_client):
    from proxmox_mcp.tools.network import get_vm_firewall_rules

    rules = [{"pos": 0, "type": "in", "action": "DROP", "proto": "tcp", "dport": "3389"}]
    mock_client.api_call = AsyncMock(return_value=rules)
    result = await get_vm_firewall_rules(vmid=100)

    assert result["status"] == "success"
    assert result["vmid"] == 100
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_get_vm_firewall_rules_fallback_to_lxc(mock_client):
    from proxmox_mcp.tools.network import get_vm_firewall_rules

    lxc_rules = [{"pos": 0, "type": "in", "action": "ACCEPT", "proto": "tcp", "dport": "80"}]
    # First call (QEMU) fails, second (LXC) succeeds
    mock_client.api_call = AsyncMock(side_effect=[Exception("404 not found"), lxc_rules])
    result = await get_vm_firewall_rules(vmid=200)

    assert result["status"] == "success"
    assert result["vmid"] == 200
    assert result["total"] == 1
    assert result["rules"] == lxc_rules


@pytest.mark.asyncio
async def test_get_vm_firewall_rules_error(mock_client):
    from proxmox_mcp.tools.network import get_vm_firewall_rules

    mock_client.api_call = AsyncMock(side_effect=Exception("Both APIs failed"))
    result = await get_vm_firewall_rules(vmid=100)

    assert result["status"] == "error"


# --- get_vm_interfaces ---


@pytest.mark.asyncio
async def test_get_vm_interfaces(mock_client):
    from proxmox_mcp.tools.network import get_vm_interfaces

    ifaces = {"result": [{"name": "eth0", "ip-addresses": [{"ip-address": "10.0.0.5"}]}]}
    mock_client.api_call = AsyncMock(return_value=ifaces)
    result = await get_vm_interfaces(vmid=100)

    assert result["status"] == "success"
    assert result["vmid"] == 100
    assert len(result["interfaces"]) == 1


@pytest.mark.asyncio
async def test_get_vm_interfaces_fallback_to_lxc(mock_client):
    from proxmox_mcp.tools.network import get_vm_interfaces

    lxc_ifaces = [{"name": "eth0", "hwaddr": "AA:BB:CC:DD:EE:FF"}]
    mock_client.api_call = AsyncMock(side_effect=[Exception("does not exist"), lxc_ifaces])
    result = await get_vm_interfaces(vmid=200)

    assert result["status"] == "success"
    assert result["interfaces"] == lxc_ifaces


@pytest.mark.asyncio
async def test_get_vm_interfaces_error(mock_client):
    from proxmox_mcp.tools.network import get_vm_interfaces

    mock_client.api_call = AsyncMock(side_effect=Exception("VM not running"))
    result = await get_vm_interfaces(vmid=100)

    assert result["status"] == "error"
    assert "suggestion" in result


# --- create_node_firewall_rule ---


@pytest.mark.asyncio
async def test_create_node_firewall_rule(mock_client):
    from proxmox_mcp.tools.network import create_node_firewall_rule

    mock_client.api_call = AsyncMock(return_value=None)
    result = await create_node_firewall_rule(
        node="pve1", action="ACCEPT", type="in", proto="tcp", dport="22"
    )
    assert result["status"] == "success"
    assert result["rule"]["action"] == "ACCEPT"
    assert result["rule"]["dport"] == "22"


@pytest.mark.asyncio
async def test_create_node_firewall_rule_invalid_action(mock_client):
    from proxmox_mcp.tools.network import create_node_firewall_rule

    result = await create_node_firewall_rule(node="pve1", action="ALLOW", type="in")
    assert result["status"] == "error"
    assert "ALLOW" in result["message"]


@pytest.mark.asyncio
async def test_create_node_firewall_rule_dry_run(mock_client):
    from proxmox_mcp.tools.network import create_node_firewall_rule

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await create_node_firewall_rule(node="pve1", action="ACCEPT", type="in")
    assert result["status"] == "dry_run"


# --- delete_node_firewall_rule ---


@pytest.mark.asyncio
async def test_delete_node_firewall_rule_requires_confirm(mock_client):
    from proxmox_mcp.tools.network import delete_node_firewall_rule

    result = await delete_node_firewall_rule(node="pve1", pos=0)
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_delete_node_firewall_rule_confirmed(mock_client):
    from proxmox_mcp.tools.network import delete_node_firewall_rule

    mock_client.api_call = AsyncMock(return_value=None)
    result = await delete_node_firewall_rule(node="pve1", pos=0, confirm=True)
    assert result["status"] == "success"
    assert result["deleted_pos"] == 0


# --- create_vm_firewall_rule ---


@pytest.mark.asyncio
async def test_create_vm_firewall_rule(mock_client):
    from proxmox_mcp.tools.network import create_vm_firewall_rule

    mock_client.api_call = AsyncMock(return_value=None)
    result = await create_vm_firewall_rule(
        vmid=100, action="DROP", type="in", proto="tcp", dport="3389"
    )
    assert result["status"] == "success"
    assert result["vmid"] == 100
    assert result["rule"]["action"] == "DROP"


@pytest.mark.asyncio
async def test_create_vm_firewall_rule_protected(mock_client):
    from proxmox_mcp.tools.network import create_vm_firewall_rule
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await create_vm_firewall_rule(vmid=100, action="ACCEPT", type="in")
    assert result["status"] == "error"


# --- delete_vm_firewall_rule ---


@pytest.mark.asyncio
async def test_delete_vm_firewall_rule_requires_confirm(mock_client):
    from proxmox_mcp.tools.network import delete_vm_firewall_rule

    result = await delete_vm_firewall_rule(vmid=100, pos=0)
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_delete_vm_firewall_rule_confirmed(mock_client):
    from proxmox_mcp.tools.network import delete_vm_firewall_rule

    mock_client.api_call = AsyncMock(return_value=None)
    result = await delete_vm_firewall_rule(vmid=100, pos=0, confirm=True)
    assert result["status"] == "success"
    assert result["deleted_pos"] == 0


# ---------------------------------------------------------------------------
# Regression tests (phase 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_vm_firewall_rules_non_404_no_fallback(mock_client):
    from proxmox_mcp.tools.network import get_vm_firewall_rules

    mock_client.api_call = AsyncMock(side_effect=Exception("403 forbidden"))
    result = await get_vm_firewall_rules(vmid=100)
    assert result["status"] == "error"
    assert "resource type mismatch" in result.get("suggestion", "")
    assert mock_client.api_call.call_count == 1


@pytest.mark.asyncio
async def test_get_vm_interfaces_non_404_no_fallback(mock_client):
    from proxmox_mcp.tools.network import get_vm_interfaces

    mock_client.api_call = AsyncMock(side_effect=Exception("500 internal error"))
    result = await get_vm_interfaces(vmid=100)
    assert result["status"] == "error"
    assert "resource type mismatch" in result.get("suggestion", "")
    assert mock_client.api_call.call_count == 1
