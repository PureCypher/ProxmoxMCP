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

    mock_server = MagicMock()
    mock_server.mcp = mock_mcp
    mock_server.proxmox_client = MagicMock()

    # Pre-populate sys.modules so imports resolve to our mocks
    sys.modules.setdefault("proxmox_mcp.server", mock_server)

    yield mock_server

    # Don't remove -- other tests may have loaded the real module
