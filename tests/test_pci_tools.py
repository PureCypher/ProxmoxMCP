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


async def test_list_node_pci_devices(mock_client):
    from proxmox_mcp.tools.pci import list_node_pci_devices

    mock_client.api_call = AsyncMock(return_value=[SAMPLE_DEVICE])
    result = await list_node_pci_devices(node="pve1")

    assert result["status"] == "success"
    assert result["node"] == "pve1"
    assert result["total"] == 1
    assert result["devices"] == [SAMPLE_DEVICE]


async def test_list_node_pci_devices_error(mock_client):
    from proxmox_mcp.tools.pci import list_node_pci_devices

    mock_client.api_call = AsyncMock(side_effect=Exception("node unreachable"))
    result = await list_node_pci_devices(node="pve1")

    assert result["status"] == "error"


# --- list_pci_mappings ---


async def test_list_pci_mappings(mock_client):
    from proxmox_mcp.tools.pci import list_pci_mappings

    mappings = [{"id": "gpu0", "map": ["node=pve1,path=0000:01:00.0"]}]
    mock_client.api_call = AsyncMock(return_value=mappings)
    result = await list_pci_mappings()

    assert result["status"] == "success"
    assert result["total"] == 1
    assert result["mappings"] == mappings


async def test_list_pci_mappings_empty(mock_client):
    from proxmox_mcp.tools.pci import list_pci_mappings

    mock_client.api_call = AsyncMock(return_value=[])
    result = await list_pci_mappings()

    assert result["status"] == "success"
    assert result["total"] == 0


# --- create_pci_mapping ---


async def test_create_pci_mapping_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    result = await create_pci_mapping(mapping_id="gpu0", node="pve1", path="01:00.0")
    assert result["status"] == "confirmation_required"


async def test_create_pci_mapping_confirmed(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.api_call = AsyncMock(side_effect=[[SAMPLE_DEVICE], None])
    result = await create_pci_mapping(mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True)

    assert result["status"] == "success"
    assert result["mapping_id"] == "gpu0"
    assert "node=pve1" in result["map_entry"]
    assert "path=01:00.0" in result["map_entry"]
    assert "id=10de:1eb8" in result["map_entry"]
    assert "iommu-group=45" in result["map_entry"]


async def test_create_pci_mapping_device_not_found(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.api_call = AsyncMock(return_value=[])
    result = await create_pci_mapping(mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True)

    assert result["status"] == "error"


async def test_create_pci_mapping_dry_run(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await create_pci_mapping(mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True)
    assert result["status"] == "dry_run"


async def test_create_pci_mapping_invalid_id(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    result = await create_pci_mapping(mapping_id="0bad", node="pve1", path="01:00.0", confirm=True)
    assert result["status"] == "error"


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


async def test_add_pci_mapping_target_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import add_pci_mapping_target

    result = await add_pci_mapping_target(mapping_id="gpu0", node="pve2", path="01:00.0")
    assert result["status"] == "confirmation_required"


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


async def test_delete_pci_mapping_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    result = await delete_pci_mapping(mapping_id="gpu0")
    assert result["status"] == "confirmation_required"


async def test_delete_pci_mapping_confirmed(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    mock_client.api_call = AsyncMock(return_value=None)
    result = await delete_pci_mapping(mapping_id="gpu0", confirm=True)

    assert result["status"] == "success"
    assert result["deleted"] is True


async def test_delete_pci_mapping_dry_run(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await delete_pci_mapping(mapping_id="gpu0", confirm=True)
    assert result["status"] == "dry_run"


async def test_delete_pci_mapping_invalid_id(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    result = await delete_pci_mapping(mapping_id="0bad", confirm=True)
    assert result["status"] == "error"


# --- assign_pci_device ---


async def test_assign_pci_device_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device

    result = await assign_pci_device(vmid=100, slot=0, mapping_id="gpu0")
    assert result["status"] == "confirmation_required"


async def test_assign_pci_device_confirmed(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device

    mock_client.api_call = AsyncMock(return_value=None)
    result = await assign_pci_device(vmid=100, slot=0, mapping_id="gpu0", confirm=True)

    assert result["status"] == "success"
    assert result["vmid"] == 100
    assert result["node"] == "pve1"
    assert result["slot"] == 0
    assert "mapping=gpu0" in result["config_value"]
    assert "pcie=1" in result["config_value"]
    assert "rombar=1" in result["config_value"]
    assert "x-vga=0" in result["config_value"]


async def test_assign_pci_device_protected(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await assign_pci_device(vmid=100, slot=0, mapping_id="gpu0", confirm=True)
    assert result["status"] == "error"


async def test_assign_pci_device_invalid_slot(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device

    result = await assign_pci_device(vmid=100, slot=99, mapping_id="gpu0", confirm=True)
    assert result["status"] == "error"


async def test_assign_pci_device_dry_run(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await assign_pci_device(vmid=100, slot=0, mapping_id="gpu0", confirm=True)
    assert result["status"] == "dry_run"


# --- remove_pci_device ---


async def test_remove_pci_device_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import remove_pci_device

    result = await remove_pci_device(vmid=100, slot=0)
    assert result["status"] == "confirmation_required"


async def test_remove_pci_device_confirmed(mock_client):
    from proxmox_mcp.tools.pci import remove_pci_device

    mock_client.api_call = AsyncMock(return_value=None)
    result = await remove_pci_device(vmid=100, slot=0, confirm=True)

    assert result["status"] == "success"
    assert result["vmid"] == 100
    assert result["slot"] == 0
    call_kwargs = mock_client.api_call.call_args.kwargs
    assert call_kwargs["delete"] == "hostpci0"


async def test_remove_pci_device_protected(mock_client):
    from proxmox_mcp.tools.pci import remove_pci_device
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await remove_pci_device(vmid=100, slot=0, confirm=True)
    assert result["status"] == "error"
