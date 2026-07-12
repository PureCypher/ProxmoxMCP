"""Tests for PCI passthrough and hardware mapping tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.pci.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.is_dry_run = False
        client.resolve_node = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


SAMPLE_DEVICE = {
    "id": "0000:01:00.0",
    "vendor": "0x10de",
    "device": "0x1eb8",
    "device_name": "TU104GL [Tesla T4]",
    "iommugroup": 45,
    "class": "0x030200",
}


# --- list_node_pci_devices ---


@pytest.mark.asyncio
async def test_list_node_pci_devices(mock_client):
    from proxmox_mcp.tools.pci import list_node_pci_devices

    mock_client.api_call = AsyncMock(return_value=[SAMPLE_DEVICE])
    result = await list_node_pci_devices(node="pve1")

    assert result["status"] == "success"
    assert result["node"] == "pve1"
    assert result["total"] == 1
    assert result["devices"] == [SAMPLE_DEVICE]


@pytest.mark.asyncio
async def test_list_node_pci_devices_error(mock_client):
    from proxmox_mcp.tools.pci import list_node_pci_devices

    mock_client.api_call = AsyncMock(side_effect=Exception("node unreachable"))
    result = await list_node_pci_devices(node="pve1")

    assert result["status"] == "error"


# --- list_pci_mappings ---


@pytest.mark.asyncio
async def test_list_pci_mappings(mock_client):
    from proxmox_mcp.tools.pci import list_pci_mappings

    mappings = [{"id": "gpu0", "map": ["node=pve1,path=0000:01:00.0"]}]
    mock_client.api_call = AsyncMock(return_value=mappings)
    result = await list_pci_mappings()

    assert result["status"] == "success"
    assert result["total"] == 1
    assert result["mappings"] == mappings


@pytest.mark.asyncio
async def test_list_pci_mappings_empty(mock_client):
    from proxmox_mcp.tools.pci import list_pci_mappings

    mock_client.api_call = AsyncMock(return_value=[])
    result = await list_pci_mappings()

    assert result["status"] == "success"
    assert result["total"] == 0
