"""Tests for node tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxmox_mcp.utils.errors import NodeNotAllowedError


@pytest.fixture
def mock_client():
    """Create a mock ProxmoxClient with api_call as AsyncMock."""
    client = MagicMock()
    client.api_call = AsyncMock()
    client.validate_node = MagicMock()  # No-op by default (no allowlist)
    return client


# --- list_nodes ---


@pytest.mark.asyncio
async def test_list_nodes(mock_client):
    from proxmox_mcp.tools.node import list_nodes

    mock_client.api_call.return_value = [
        {
            "node": "pve1",
            "status": "online",
            "cpu": 0.15,
            "maxcpu": 8,
            "mem": 4 * 1024**3,
            "maxmem": 16 * 1024**3,
            "disk": 50 * 1024**3,
            "maxdisk": 500 * 1024**3,
            "uptime": 86400 + 3600 + 120,
        },
        {
            "node": "pve2",
            "status": "online",
            "cpu": 0.02,
            "maxcpu": 4,
            "mem": 1 * 1024**3,
            "maxmem": 8 * 1024**3,
            "disk": 10 * 1024**3,
            "maxdisk": 200 * 1024**3,
            "uptime": 3600,
        },
    ]

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await list_nodes()

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["nodes"][0]["node"] == "pve1"
    assert result["nodes"][0]["cpu_usage_percent"] == 15.0
    assert result["nodes"][0]["cpu_cores"] == 8
    assert "GB" in result["nodes"][0]["memory_used"]
    assert "1d" in result["nodes"][0]["uptime"]


@pytest.mark.asyncio
async def test_list_nodes_empty(mock_client):
    from proxmox_mcp.tools.node import list_nodes

    mock_client.api_call.return_value = []

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await list_nodes()

    assert result["status"] == "success"
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_list_nodes_error(mock_client):
    from proxmox_mcp.tools.node import list_nodes

    mock_client.api_call.side_effect = Exception("connection lost")

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await list_nodes()

    assert result["status"] == "error"
    assert "connection lost" in result["message"]


# --- get_node_status ---


@pytest.mark.asyncio
async def test_get_node_status(mock_client):
    from proxmox_mcp.tools.node import get_node_status

    mock_client.api_call.return_value = {
        "cpu": 0.1,
        "memory": {"total": 16 * 1024**3, "used": 4 * 1024**3},
        "uptime": 86400,
        "kversion": "Linux 6.2.16-3-pve",
        "loadavg": ["0.5", "0.3", "0.2"],
    }

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_status("pve1")

    assert result["status"] == "success"
    assert result["node"] == "pve1"
    assert result["data"]["uptime"] == 86400
    mock_client.validate_node.assert_called_once_with("pve1")


@pytest.mark.asyncio
async def test_get_node_status_not_allowed(mock_client):
    from proxmox_mcp.tools.node import get_node_status

    mock_client.validate_node.side_effect = NodeNotAllowedError(
        "Node 'pve3' is not in the allowed nodes list: ['pve1', 'pve2']"
    )

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_status("pve3")

    assert result["status"] == "error"
    assert result["error_type"] == "NodeNotAllowedError"
    assert "pve3" in result["message"]


@pytest.mark.asyncio
async def test_get_node_status_invalid_name():
    from proxmox_mcp.tools.node import get_node_status

    result = await get_node_status("  ")

    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"


# --- get_node_services ---


@pytest.mark.asyncio
async def test_get_node_services(mock_client):
    from proxmox_mcp.tools.node import get_node_services

    mock_client.api_call.return_value = [
        {"service": "pvedaemon", "state": "running", "name": "PVE API daemon"},
        {"service": "pveproxy", "state": "running", "name": "PVE Proxy Server"},
    ]

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_services("pve1")

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["node"] == "pve1"


# --- get_node_network ---


@pytest.mark.asyncio
async def test_get_node_network(mock_client):
    from proxmox_mcp.tools.node import get_node_network

    mock_client.api_call.return_value = [
        {"iface": "vmbr0", "type": "bridge", "address": "10.0.0.1"},
        {"iface": "eth0", "type": "eth", "address": "192.168.1.1"},
    ]

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_network("pve1")

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["interfaces"][0]["iface"] == "vmbr0"


# --- get_node_storage ---


@pytest.mark.asyncio
async def test_get_node_storage(mock_client):
    from proxmox_mcp.tools.node import get_node_storage

    mock_client.api_call.return_value = [
        {"storage": "local", "type": "dir", "active": 1, "enabled": 1},
        {"storage": "local-lvm", "type": "lvmthin", "active": 1, "enabled": 1},
    ]

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_storage("pve1")

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["storage"][0]["storage"] == "local"


# --- get_node_syslog ---


@pytest.mark.asyncio
async def test_get_node_syslog(mock_client):
    from proxmox_mcp.tools.node import get_node_syslog

    mock_client.api_call.return_value = [
        {"t": "Jan  1 00:00:01", "n": 1, "d": "pve1 systemd[1]: Started foo"},
        {"t": "Jan  1 00:00:02", "n": 2, "d": "pve1 systemd[1]: Started bar"},
    ]

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_syslog("pve1", limit=10)

    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["node"] == "pve1"


@pytest.mark.asyncio
async def test_get_node_syslog_with_since(mock_client):
    from proxmox_mcp.tools.node import get_node_syslog

    mock_client.api_call.return_value = [
        {"t": "Jan  2 00:00:01", "n": 1, "d": "pve1 systemd[1]: Started baz"},
    ]

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_syslog("pve1", limit=10, since="1704067200")

    assert result["status"] == "success"
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_get_node_syslog_since_int(mock_client):
    from proxmox_mcp.tools.node import get_node_syslog

    mock_client.api_call.return_value = []

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_syslog("pve1", limit=10, since=1704067200)

    assert result["status"] == "success"
    mock_client.api_call.assert_called_once_with(
        mock_client.api.nodes("pve1").syslog.get, limit=10, since=1704067200
    )


@pytest.mark.asyncio
async def test_get_node_syslog_since_date_string_rejected(mock_client):
    from proxmox_mcp.tools.node import get_node_syslog

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_syslog("pve1", limit=10, since="2024-01-02")

    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"
    assert "unix epoch" in result["message"]
    mock_client.api_call.assert_not_called()


@pytest.mark.asyncio
async def test_get_node_syslog_limit_clamped(mock_client):
    from proxmox_mcp.tools.node import get_node_syslog

    mock_client.api_call.return_value = []

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await get_node_syslog("pve1", limit=999999)

    assert result["status"] == "success"
    mock_client.api_call.assert_called_once_with(
        mock_client.api.nodes("pve1").syslog.get, limit=10000
    )


# --- reboot_node ---


@pytest.mark.asyncio
async def test_reboot_node_requires_confirm(mock_client):
    from proxmox_mcp.tools.node import reboot_node

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await reboot_node("pve1")

    assert result["status"] == "confirmation_required"
    assert "REBOOT" in result["warning"]


@pytest.mark.asyncio
async def test_reboot_node_confirmed(mock_client):
    from proxmox_mcp.tools.node import reboot_node

    mock_client.api_call.return_value = "UPID:pve1:00001:reboot"
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await reboot_node("pve1", confirm=True)

    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_reboot_node_dry_run(mock_client):
    from proxmox_mcp.tools.node import reboot_node

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await reboot_node("pve1", confirm=True)

    assert result["status"] == "dry_run"


# --- shutdown_node ---


@pytest.mark.asyncio
async def test_shutdown_node_requires_confirm(mock_client):
    from proxmox_mcp.tools.node import shutdown_node

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await shutdown_node("pve1")

    assert result["status"] == "confirmation_required"
    assert "SHUT DOWN" in result["warning"]


@pytest.mark.asyncio
async def test_shutdown_node_confirmed(mock_client):
    from proxmox_mcp.tools.node import shutdown_node

    mock_client.api_call.return_value = "UPID:pve1:00002:shutdown"
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await shutdown_node("pve1", confirm=True)

    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_shutdown_node_not_allowed(mock_client):
    from proxmox_mcp.tools.node import shutdown_node

    mock_client.validate_node.side_effect = NodeNotAllowedError("not allowed")

    with patch("proxmox_mcp.tools.node.get_client", return_value=mock_client):
        result = await shutdown_node("pve3", confirm=True)

    assert result["status"] == "error"
