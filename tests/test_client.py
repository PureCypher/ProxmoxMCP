from unittest.mock import MagicMock, patch

import pytest

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.utils.errors import (
    InvalidParameterError,
    NodeNotAllowedError,
    ProtectedResourceError,
    VMNotFoundError,
)


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setenv("PROXMOX_TOKEN_NAME", "root@pam!tok")
    monkeypatch.setenv("PROXMOX_TOKEN_VALUE", "fake-token")
    return ProxmoxConfig()


@pytest.fixture
def client(mock_config):
    with patch("proxmox_mcp.client.ProxmoxAPI") as mock_api_cls:
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        c = ProxmoxClient(mock_config)
        c._api = mock_api
        return c


@pytest.mark.asyncio
async def test_resolve_node_for_vmid(client):
    client._api.cluster.resources.get.return_value = [
        {"vmid": 100, "node": "pve1", "type": "qemu"},
        {"vmid": 200, "node": "pve2", "type": "lxc"},
    ]
    node = await client.resolve_node_for_vmid(100)
    assert node == "pve1"


@pytest.mark.asyncio
async def test_resolve_node_for_vmid_not_found(client):
    client._api.cluster.resources.get.return_value = []
    with pytest.raises(VMNotFoundError):
        await client.resolve_node_for_vmid(999)


def test_check_protected_raises(mock_config, monkeypatch):
    monkeypatch.setenv("PROXMOX_PROTECTED_VMIDS", "100,101")
    config = ProxmoxConfig()
    with patch("proxmox_mcp.client.ProxmoxAPI"):
        c = ProxmoxClient(config)
        with pytest.raises(ProtectedResourceError):
            c.check_protected(100)


def test_check_protected_allows(client):
    client.check_protected(999)  # Should not raise


def test_validate_node_allowed(mock_config, monkeypatch):
    monkeypatch.setenv("PROXMOX_ALLOWED_NODES", "pve1,pve2")
    config = ProxmoxConfig()
    with patch("proxmox_mcp.client.ProxmoxAPI"):
        c = ProxmoxClient(config)
        c.validate_node("pve1")  # Should not raise
        with pytest.raises(NodeNotAllowedError):
            c.validate_node("pve3")


def test_validate_node_no_allowlist(client):
    client.validate_node("anything")  # Empty allowlist = all allowed


def test_dry_run_response(client):
    result = client.dry_run_response("delete_vm", vmid=100, node="pve1")
    assert result["status"] == "dry_run"
    assert result["action"] == "delete_vm"
    assert result["params"]["vmid"] == 100


def test_dry_run_response_with_action_param(client):
    """Regression: params containing a key literally named 'action' (e.g. firewall
    rule action ACCEPT/DROP/REJECT) must not collide with the tool_name argument."""
    result = client.dry_run_response("create_vm_firewall_rule", vmid=100, action="ACCEPT")
    assert result["status"] == "dry_run"
    assert result["action"] == "create_vm_firewall_rule"
    assert result["params"]["action"] == "ACCEPT"


@pytest.mark.asyncio
async def test_resolve_node_with_explicit_node(client):
    node = await client.resolve_node(100, "pve1")
    assert node == "pve1"


@pytest.mark.asyncio
async def test_resolve_node_auto_detect(client):
    client._api.cluster.resources.get.return_value = [
        {"vmid": 100, "node": "pve2", "type": "qemu"},
    ]
    node = await client.resolve_node(100, None)
    assert node == "pve2"


@pytest.mark.asyncio
async def test_resolve_node_invalid_name(client):
    with pytest.raises(InvalidParameterError):
        await client.resolve_node(100, "bad node!")


@pytest.mark.asyncio
async def test_resolve_node_disallowed_node(mock_config, monkeypatch):
    monkeypatch.setenv("PROXMOX_ALLOWED_NODES", "pve1,pve2")
    config = ProxmoxConfig()
    with patch("proxmox_mcp.client.ProxmoxAPI"):
        c = ProxmoxClient(config)
        with pytest.raises(NodeNotAllowedError):
            await c.resolve_node(100, "pve3")


@pytest.mark.asyncio
async def test_client_init_token_auth(mock_config):
    with patch("proxmox_mcp.client.ProxmoxAPI") as mock_cls:
        ProxmoxClient(mock_config)
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["user"] == "root@pam"
        assert call_kwargs["token_name"] == "tok"
        assert call_kwargs["token_value"] == "fake-token"


# --- api_call error mapping ---


def _api_error(status_code: int):
    from proxmoxer.core import ResourceException

    return ResourceException(status_code, "err", "body detail with host pve1.example.com")


@pytest.mark.asyncio
async def test_api_call_401_maps_to_authentication_error(client):
    from proxmox_mcp.utils.errors import AuthenticationError

    client._api.version.get.side_effect = _api_error(401)
    with pytest.raises(AuthenticationError) as exc:
        await client.api_call(client._api.version.get)
    # Raw body (may echo hostnames) must not leak into the message.
    assert "pve1.example.com" not in str(exc.value)


@pytest.mark.asyncio
async def test_api_call_403_maps_to_insufficient_permissions(client):
    from proxmox_mcp.utils.errors import InsufficientPermissionsError

    client._api.version.get.side_effect = _api_error(403)
    with pytest.raises(InsufficientPermissionsError):
        await client.api_call(client._api.version.get)


@pytest.mark.asyncio
async def test_api_call_500_maps_to_proxmox_mcp_error(client):
    from proxmox_mcp.utils.errors import ProxmoxMCPError

    client._api.version.get.side_effect = _api_error(500)
    with pytest.raises(ProxmoxMCPError) as exc:
        await client.api_call(client._api.version.get)
    assert "500" in str(exc.value)
    assert "pve1.example.com" not in str(exc.value)


@pytest.mark.asyncio
async def test_api_call_network_error_maps_to_connection_error(client):
    import requests.exceptions

    from proxmox_mcp.utils.errors import ProxmoxConnectionError

    client._api.version.get.side_effect = requests.exceptions.ConnectionError("boom")
    with pytest.raises(ProxmoxConnectionError):
        await client.api_call(client._api.version.get)


@pytest.mark.asyncio
async def test_api_call_timeout_maps_to_connection_error(client):
    from proxmox_mcp.utils.errors import ProxmoxConnectionError

    client._api.version.get.side_effect = TimeoutError("timed out")
    with pytest.raises(ProxmoxConnectionError):
        await client.api_call(client._api.version.get)


# --- node resolution cache ---


@pytest.mark.asyncio
async def test_resolve_node_for_vmid_uses_cache_within_ttl(client):
    client._api.cluster.resources.get.return_value = [
        {"vmid": 100, "node": "pve1", "type": "qemu"},
    ]
    node1 = await client.resolve_node_for_vmid(100)
    node2 = await client.resolve_node_for_vmid(100)
    assert node1 == node2 == "pve1"
    # Second call within TTL must be served from the cache.
    assert client._api.cluster.resources.get.call_count == 1


@pytest.mark.asyncio
async def test_resolve_node_for_vmid_cache_expires(client):
    client._api.cluster.resources.get.return_value = [
        {"vmid": 100, "node": "pve1", "type": "qemu"},
    ]
    await client.resolve_node_for_vmid(100)
    # Age the cached entry beyond the TTL.
    node, stamped = client._node_cache[100]
    client._node_cache[100] = (node, stamped - 31)
    await client.resolve_node_for_vmid(100)
    assert client._api.cluster.resources.get.call_count == 2


# --- token format validation ---


def test_token_without_bang_requires_proxmox_user(mock_config, monkeypatch):
    monkeypatch.setenv("PROXMOX_TOKEN_NAME", "just-a-token-id")
    monkeypatch.delenv("PROXMOX_USER", raising=False)
    config = ProxmoxConfig()
    from proxmox_mcp.utils.errors import AuthenticationError

    with pytest.raises(AuthenticationError) as exc:
        ProxmoxClient(config)
    assert "PROXMOX_USER must be set" in str(exc.value)
