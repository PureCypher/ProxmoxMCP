import pytest
from unittest.mock import MagicMock, patch
from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.utils.errors import (
    VMNotFoundError,
    ProtectedResourceError,
    NodeNotAllowedError,
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


@pytest.mark.asyncio
async def test_client_init_token_auth(mock_config):
    with patch("proxmox_mcp.client.ProxmoxAPI") as mock_cls:
        ProxmoxClient(mock_config)
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["token_name"] == "root@pam!tok"
        assert call_kwargs["token_value"] == "fake-token"
