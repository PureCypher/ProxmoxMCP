"""Tests for cluster tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Create a mock ProxmoxClient with api_call as AsyncMock."""
    client = MagicMock()
    client.api_call = AsyncMock()
    return client


# --- get_cluster_status ---


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


async def test_get_cluster_status_error(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_status

    mock_client.api_call.side_effect = Exception("Connection refused")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_status()

    assert result["status"] == "error"
    assert "Connection refused" in result["message"]


# --- get_cluster_resources ---


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


async def test_get_cluster_resources_error(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_resources

    mock_client.api_call.side_effect = Exception("API error")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_resources()

    assert result["status"] == "error"


# --- get_cluster_log ---


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


async def test_get_cluster_log_error(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_log

    mock_client.api_call.side_effect = Exception("timeout")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_cluster_log()

    assert result["status"] == "error"


# --- get_next_vmid ---


async def test_get_next_vmid(mock_client):
    from proxmox_mcp.tools.cluster import get_next_vmid

    mock_client.api_call.return_value = "105"

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_next_vmid()

    assert result["status"] == "success"
    assert result["vmid"] == 105
    assert isinstance(result["vmid"], int)


async def test_get_next_vmid_error(mock_client):
    from proxmox_mcp.tools.cluster import get_next_vmid

    mock_client.api_call.side_effect = Exception("cluster error")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await get_next_vmid()

    assert result["status"] == "error"


# --- list_pools ---


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


async def test_list_pools_empty(mock_client):
    from proxmox_mcp.tools.cluster import list_pools

    mock_client.api_call.return_value = []

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await list_pools()

    assert result["status"] == "success"
    assert result["count"] == 0
    assert result["pools"] == []


async def test_list_pools_error(mock_client):
    from proxmox_mcp.tools.cluster import list_pools

    mock_client.api_call.side_effect = Exception("permission denied")

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await list_pools()

    assert result["status"] == "error"


# --- create_pool ---


async def test_create_pool(mock_client):
    from proxmox_mcp.tools.cluster import create_pool

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await create_pool("dev-team", comment="Development team pool")

    assert result["status"] == "success"
    assert result["poolid"] == "dev-team"


async def test_create_pool_dry_run(mock_client):
    from proxmox_mcp.tools.cluster import create_pool

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await create_pool("dev-team")

    assert result["status"] == "dry_run"


# --- modify_pool ---


async def test_modify_pool_add_vms(mock_client):
    from proxmox_mcp.tools.cluster import modify_pool

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await modify_pool("dev-team", vms="100,101")

    assert result["status"] == "success"
    assert "vms" in result["changes"]


async def test_modify_pool_no_changes(mock_client):
    from proxmox_mcp.tools.cluster import modify_pool

    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await modify_pool("dev-team")

    assert result["status"] == "error"


# --- delete_pool ---


async def test_delete_pool_requires_confirm(mock_client):
    from proxmox_mcp.tools.cluster import delete_pool

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await delete_pool("dev-team")

    assert result["status"] == "confirmation_required"


async def test_delete_pool_confirmed(mock_client):
    from proxmox_mcp.tools.cluster import delete_pool

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await delete_pool("dev-team", confirm=True)

    assert result["status"] == "success"
    assert result["poolid"] == "dev-team"


async def test_delete_pool_error(mock_client):
    from proxmox_mcp.tools.cluster import delete_pool

    mock_client.api_call.side_effect = Exception("pool not empty")
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await delete_pool("dev-team", confirm=True)

    assert result["status"] == "error"


# --- list_users ---


async def test_list_users(mock_client):
    from proxmox_mcp.tools.cluster import list_users

    mock_client.api_call.return_value = [
        {"userid": "root@pam", "enable": 1, "email": "root@example.com"},
        {"userid": "admin@pve", "enable": 1},
    ]

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await list_users()

    assert result["status"] == "success"
    assert result["count"] == 2


# --- create_user ---


async def test_create_user(mock_client):
    from proxmox_mcp.tools.cluster import create_user

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await create_user(
            userid="john@pve",
            password="secret",
            email="john@example.com",
            confirm=True,
        )

    assert result["status"] == "success"
    assert result["userid"] == "john@pve"


# --- delete_user ---


async def test_delete_user_requires_confirm(mock_client):
    from proxmox_mcp.tools.cluster import delete_user

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await delete_user("john@pve")

    assert result["status"] == "confirmation_required"


async def test_delete_user_confirmed(mock_client):
    from proxmox_mcp.tools.cluster import delete_user

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await delete_user("john@pve", confirm=True)

    assert result["status"] == "success"


# --- list_roles ---


async def test_list_roles(mock_client):
    from proxmox_mcp.tools.cluster import list_roles

    mock_client.api_call.return_value = [
        {"roleid": "PVEAdmin", "privs": "Sys.Audit,Sys.Modify"},
        {"roleid": "PVEVMUser", "privs": "VM.Audit,VM.Console"},
    ]

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await list_roles()

    assert result["status"] == "success"
    assert result["count"] == 2


# --- set_user_permission ---


async def test_set_user_permission(mock_client):
    from proxmox_mcp.tools.cluster import set_user_permission

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False
    mock_client.api_call = AsyncMock(return_value=[{"roleid": "PVEVMUser"}])

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await set_user_permission(
            path="/vms/100", roles="PVEVMUser", users="john@pve", confirm=True
        )

    assert result["status"] == "success"
    assert result["path"] == "/vms/100"


async def test_set_user_permission_requires_users_or_groups(mock_client):
    from proxmox_mcp.tools.cluster import set_user_permission

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await set_user_permission(path="/", roles="PVEAdmin")

    assert result["status"] == "error"


# --- list_ha_resources ---


async def test_list_ha_resources(mock_client):
    from proxmox_mcp.tools.cluster import list_ha_resources

    mock_client.api_call.return_value = [
        {"sid": "vm:100", "state": "started", "group": "ha-group1"},
    ]

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await list_ha_resources()

    assert result["status"] == "success"
    assert result["count"] == 1


# --- create_ha_resource ---


async def test_create_ha_resource(mock_client):
    from proxmox_mcp.tools.cluster import create_ha_resource

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await create_ha_resource(sid="vm:100", state="started")

    assert result["status"] == "success"
    assert result["sid"] == "vm:100"


async def test_create_ha_resource_invalid_state(mock_client):
    from proxmox_mcp.tools.cluster import create_ha_resource

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await create_ha_resource(sid="vm:100", state="running")

    assert result["status"] == "error"


# --- modify_ha_resource ---


async def test_modify_ha_resource(mock_client):
    from proxmox_mcp.tools.cluster import modify_ha_resource

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await modify_ha_resource(sid="vm:100", state="stopped")

    assert result["status"] == "success"
    assert "state" in result["changes"]


async def test_modify_ha_resource_no_changes(mock_client):
    from proxmox_mcp.tools.cluster import modify_ha_resource

    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await modify_ha_resource(sid="vm:100")

    assert result["status"] == "error"


# --- delete_ha_resource ---


async def test_delete_ha_resource_requires_confirm(mock_client):
    from proxmox_mcp.tools.cluster import delete_ha_resource

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await delete_ha_resource(sid="vm:100")

    assert result["status"] == "confirmation_required"


async def test_delete_ha_resource_confirmed(mock_client):
    from proxmox_mcp.tools.cluster import delete_ha_resource

    mock_client.api_call.return_value = None
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await delete_ha_resource(sid="vm:100", confirm=True)

    assert result["status"] == "success"
    assert result["sid"] == "vm:100"


# ---------------------------------------------------------------------------
# Regression tests (phase 3)
# ---------------------------------------------------------------------------


async def test_create_user_requires_confirm(mock_client):
    from proxmox_mcp.tools.cluster import create_user

    mock_client.api_call = AsyncMock(return_value=None)
    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await create_user(userid="john@pve", password="secret")
    assert result["status"] == "confirmation_required"
    mock_client.api_call.assert_not_called()


async def test_get_cluster_log_clamps_max_entries(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_log

    mock_client.api_call = AsyncMock(return_value=[])
    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        await get_cluster_log(max_entries=5000)
    assert mock_client.api_call.call_args.kwargs.get("max") == 1000


async def test_set_user_permission_requires_confirm(mock_client):
    from proxmox_mcp.tools.cluster import set_user_permission

    mock_client.api_call = AsyncMock(return_value=[{"roleid": "PVEVMUser"}])
    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await set_user_permission(path="/", roles="PVEVMUser", users="john@pve")
    assert result["status"] == "confirmation_required"


async def test_set_user_permission_unknown_role(mock_client):
    from proxmox_mcp.tools.cluster import set_user_permission

    mock_client.api_call = AsyncMock(return_value=[{"roleid": "PVEVMUser"}])
    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await set_user_permission(
            path="/", roles="NoSuchRole", users="john@pve", confirm=True
        )
    assert result["status"] == "error"
    assert "NoSuchRole" in result["message"]


async def test_set_user_permission_bad_role_chars(mock_client):
    from proxmox_mcp.tools.cluster import set_user_permission

    mock_client.api_call = AsyncMock(return_value=[])
    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await set_user_permission(
            path="/", roles="Evil;rm", users="john@pve", confirm=True
        )
    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"


async def test_set_user_permission_bad_path(mock_client):
    from proxmox_mcp.tools.cluster import set_user_permission

    mock_client.api_call = AsyncMock(return_value=[{"roleid": "PVEVMUser"}])
    with patch("proxmox_mcp.tools.cluster.get_client", return_value=mock_client):
        result = await set_user_permission(
            path="/../../etc", roles="PVEVMUser", users="john@pve", confirm=True
        )
    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"
