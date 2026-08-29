"""Shared test fixtures for tool tests.

Patches the server module to avoid needing real Proxmox config/connection
when importing tool modules.
"""

import os
import sys
from unittest.mock import MagicMock

# Dummy defaults so a bare `pytest` on a fresh clone can import proxmox_mcp
# (whose config requires PROXMOX_HOST + an auth pair). setdefault: real env
# values (or .env files) always win; nothing here is a secret.
os.environ.setdefault("PROXMOX_HOST", "test")
os.environ.setdefault("PROXMOX_TOKEN_NAME", "root@pam!dummy")
os.environ.setdefault("PROXMOX_TOKEN_VALUE", "00000000-0000-0000-0000-000000000000")

import pytest


@pytest.fixture(autouse=True, scope="session")
def no_dotenv():
    """Make config loading hermetic: no ambient .env may leak credentials into
    tests (CI has none; a developer's live .env must not change results)."""
    from proxmox_mcp.config import ProxmoxConfig

    old = ProxmoxConfig.model_config.get("env_file")
    ProxmoxConfig.model_config["env_file"] = "/nonexistent/.env.unset"
    yield
    if old is None:
        ProxmoxConfig.model_config.pop("env_file", None)
    else:
        ProxmoxConfig.model_config["env_file"] = old


@pytest.fixture(autouse=True, scope="session")
def mock_server_module():
    """Inject a mock server module so tool modules can import mcp and proxmox_client
    without requiring real config or a Proxmox connection."""
    mock_mcp = MagicMock()
    # Make @mcp.tool() a pass-through decorator
    mock_mcp.tool.return_value = lambda f: f
    # Make @mcp.resource() a pass-through decorator
    mock_mcp.resource.return_value = lambda f: f
    # Make @mcp.prompt() a pass-through decorator
    mock_mcp.prompt.return_value = lambda f: f

    mock_server = MagicMock()
    mock_server.mcp = mock_mcp
    mock_server.proxmox_client = MagicMock()

    # Pre-populate sys.modules so imports resolve to our mocks
    sys.modules.setdefault("proxmox_mcp.server", mock_server)

    yield mock_server

    # Don't remove -- other tests may have loaded the real module


@pytest.fixture()
def mock_config():
    """Provide a mock ProxmoxConfig for tests that need configuration."""
    config = MagicMock()
    config.PROXMOX_HOST = "test-host"
    config.PROXMOX_PORT = 8006
    config.PROXMOX_VERIFY_SSL = False
    config.PROXMOX_TOKEN_NAME = "test@pam!test"
    config.PROXMOX_TOKEN_VALUE = "test-token-value"
    config.PROXMOX_USER = None
    config.PROXMOX_PASSWORD = None
    config.PROXMOX_DRY_RUN = False
    config.PROXMOX_ALLOWED_NODES = ""
    config.PROXMOX_PROTECTED_VMIDS = ""
    config.MCP_TRANSPORT = "stdio"
    config.MCP_HTTP_PORT = 3001
    config.LOG_LEVEL = "INFO"
    config.allowed_nodes = []
    config.protected_vmids = []
    return config
