import pytest
from pydantic import ValidationError

from proxmox_mcp.config import ProxmoxConfig


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setenv("PROXMOX_TOKEN_NAME", "root@pam!tok")
    monkeypatch.setenv("PROXMOX_TOKEN_VALUE", "abc-123")
    config = ProxmoxConfig()
    assert config.PROXMOX_HOST == "10.0.0.1"
    assert config.PROXMOX_PORT == 8006
    assert config.PROXMOX_TOKEN_NAME == "root@pam!tok"


def test_config_defaults(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "x")
    config = ProxmoxConfig()
    assert config.PROXMOX_VERIFY_SSL is False
    assert config.PROXMOX_DRY_RUN is False
    assert config.protected_vmids == []
    assert config.allowed_nodes == []
    assert config.MCP_TRANSPORT == "stdio"
    assert config.LOG_LEVEL == "INFO"


def test_config_protected_vmids_parsing(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "x")
    monkeypatch.setenv("PROXMOX_PROTECTED_VMIDS", "100,101,102")
    config = ProxmoxConfig()
    assert config.protected_vmids == [100, 101, 102]


def test_config_allowed_nodes_parsing(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "x")
    monkeypatch.setenv("PROXMOX_ALLOWED_NODES", "pve1,pve2")
    config = ProxmoxConfig()
    assert config.allowed_nodes == ["pve1", "pve2"]


def test_config_empty_lists(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "x")
    monkeypatch.setenv("PROXMOX_PROTECTED_VMIDS", "")
    monkeypatch.setenv("PROXMOX_ALLOWED_NODES", "")
    config = ProxmoxConfig()
    assert config.protected_vmids == []
    assert config.allowed_nodes == []


def test_config_requires_host(monkeypatch):
    monkeypatch.delenv("PROXMOX_HOST", raising=False)
    with pytest.raises(ValidationError):
        ProxmoxConfig(_env_file=None)


def test_conftest_defaults_do_not_mask_missing_host(monkeypatch):
    """conftest sets dummy env via setdefault, so an explicitly missing
    PROXMOX_HOST must still fail loudly."""
    import os

    from proxmox_mcp.config import ProxmoxConfig

    assert os.environ.get("PROXMOX_HOST") == "test"
    # Simulate a fresh env where the variable truly is absent.
    monkeypatch.delenv("PROXMOX_HOST", raising=False)
    with pytest.raises(ValidationError):
        ProxmoxConfig(_env_file=None)
