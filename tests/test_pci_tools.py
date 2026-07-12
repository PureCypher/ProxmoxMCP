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


# --- create_pci_mapping ---


@pytest.mark.asyncio
async def test_create_pci_mapping_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    result = await create_pci_mapping(mapping_id="gpu0", node="pve1", path="01:00.0")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_create_pci_mapping_confirmed(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.api_call = AsyncMock(side_effect=[[SAMPLE_DEVICE], None])
    result = await create_pci_mapping(
        mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True
    )

    assert result["status"] == "success"
    assert result["mapping_id"] == "gpu0"
    assert "node=pve1" in result["map_entry"]
    assert "path=01:00.0" in result["map_entry"]
    assert "id=10de:1eb8" in result["map_entry"]
    assert "iommu-group=45" in result["map_entry"]


@pytest.mark.asyncio
async def test_create_pci_mapping_device_not_found(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.api_call = AsyncMock(return_value=[])
    result = await create_pci_mapping(
        mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True
    )

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_create_pci_mapping_dry_run(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await create_pci_mapping(
        mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True
    )
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_create_pci_mapping_invalid_id(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    result = await create_pci_mapping(
        mapping_id="0bad", node="pve1", path="01:00.0", confirm=True
    )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_create_pci_mapping_with_comment(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.api_call = AsyncMock(side_effect=[[SAMPLE_DEVICE], None])
    result = await create_pci_mapping(
        mapping_id="gpu0", node="pve1", path="01:00.0", comment="Tesla T4", confirm=True
    )
    assert result["status"] == "success"
    post_call_kwargs = mock_client.api_call.call_args_list[1].kwargs
    assert post_call_kwargs["comment"] == "Tesla T4"


# --- add_pci_mapping_target ---


@pytest.mark.asyncio
async def test_add_pci_mapping_target_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import add_pci_mapping_target

    result = await add_pci_mapping_target(mapping_id="gpu0", node="pve2", path="01:00.0")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_add_pci_mapping_target_confirmed(mock_client):
    from proxmox_mcp.tools.pci import add_pci_mapping_target

    existing = {"id": "gpu0", "map": ["node=pve1,path=0000:01:00.0,id=10de:1eb8"]}
    mock_client.api_call = AsyncMock(side_effect=[existing, [SAMPLE_DEVICE], None])
    result = await add_pci_mapping_target(
        mapping_id="gpu0", node="pve2", path="01:00.0", confirm=True
    )

    assert result["status"] == "success"
    assert result["total_targets"] == 2


# --- delete_pci_mapping ---


@pytest.mark.asyncio
async def test_delete_pci_mapping_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    result = await delete_pci_mapping(mapping_id="gpu0")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_delete_pci_mapping_confirmed(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    mock_client.api_call = AsyncMock(return_value=None)
    result = await delete_pci_mapping(mapping_id="gpu0", confirm=True)

    assert result["status"] == "success"
    assert result["deleted"] is True


@pytest.mark.asyncio
async def test_delete_pci_mapping_dry_run(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await delete_pci_mapping(mapping_id="gpu0", confirm=True)
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_delete_pci_mapping_invalid_id(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    result = await delete_pci_mapping(mapping_id="0bad", confirm=True)
    assert result["status"] == "error"
