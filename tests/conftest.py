"""Shared test fixtures for tool tests.

Patches the server module to avoid needing real Proxmox config/connection
when importing tool modules.
"""

import sys
from unittest.mock import MagicMock

import pytest


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
