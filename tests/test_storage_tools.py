"""Tests for storage tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    """Create a mock ProxmoxClient with api_call as AsyncMock."""
    client = MagicMock()
    client.api_call = AsyncMock()
    client.validate_node = MagicMock()
    return client


# --- list_storage ---


@pytest.mark.asyncio
async def test_list_storage(mock_client):
    from proxmox_mcp.tools.storage import list_storage

    mock_client.api_call.return_value = [
        {
            "storage": "local",
            "type": "dir",
            "content": "iso,vztmpl,backup",
            "shared": 0,
        },
        {
            "storage": "local-lvm",
            "type": "lvmthin",
            "content": "images,rootdir",
            "shared": 0,
        },
        {
            "storage": "ceph-pool",
            "type": "rbd",
            "content": "images",
            "shared": 1,
        },
    ]

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await list_storage()

    assert result["status"] == "success"
    assert result["count"] == 3
    assert result["storage"][0]["storage"] == "local"
    assert result["storage"][2]["shared"] == 1


@pytest.mark.asyncio
async def test_list_storage_empty(mock_client):
    from proxmox_mcp.tools.storage import list_storage

    mock_client.api_call.return_value = []

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await list_storage()

    assert result["status"] == "success"
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_list_storage_error(mock_client):
    from proxmox_mcp.tools.storage import list_storage

    mock_client.api_call.side_effect = Exception("API error")

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await list_storage()

    assert result["status"] == "error"


# --- get_storage_status ---


@pytest.mark.asyncio
async def test_get_storage_status(mock_client):
    from proxmox_mcp.tools.storage import get_storage_status

    mock_client.api_call.return_value = {
        "total": 500 * 1024**3,
        "used": 200 * 1024**3,
        "avail": 300 * 1024**3,
        "type": "dir",
        "active": 1,
        "enabled": 1,
        "content": "iso,vztmpl,backup",
    }

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await get_storage_status("pve1", "local")

    assert result["status"] == "success"
    assert result["node"] == "pve1"
    assert result["storage"] == "local"
    assert result["data"]["type"] == "dir"
    mock_client.validate_node.assert_called_once_with("pve1")


@pytest.mark.asyncio
async def test_get_storage_status_error(mock_client):
    from proxmox_mcp.tools.storage import get_storage_status

    mock_client.api_call.side_effect = Exception("storage not found")

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await get_storage_status("pve1", "nonexistent")

    assert result["status"] == "error"
    assert "storage not found" in result["message"]


# --- list_storage_content ---


@pytest.mark.asyncio
async def test_list_storage_content(mock_client):
    from proxmox_mcp.tools.storage import list_storage_content

    mock_client.api_call.return_value = [
        {
            "volid": "local:iso/ubuntu-22.04.iso",
            "format": "iso",
            "size": 3 * 1024**3,
        },
        {
            "volid": "local:iso/debian-12.iso",
            "format": "iso",
            "size": 600 * 1024**2,
        },
    ]

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await list_storage_content("pve1", "local")

    assert result["status"] == "success"
    assert result["content_type"] == "all"
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_list_storage_content_filtered(mock_client):
    from proxmox_mcp.tools.storage import list_storage_content

    mock_client.api_call.return_value = [
        {
            "volid": "local:iso/ubuntu-22.04.iso",
            "format": "iso",
            "size": 3 * 1024**3,
        },
    ]

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await list_storage_content("pve1", "local", content_type="iso")

    assert result["status"] == "success"
    assert result["content_type"] == "iso"
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_list_storage_content_error(mock_client):
    from proxmox_mcp.tools.storage import list_storage_content

    mock_client.api_call.side_effect = Exception("permission denied")

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await list_storage_content("pve1", "local")

    assert result["status"] == "error"


# --- get_available_isos ---


@pytest.mark.asyncio
async def test_get_available_isos(mock_client):
    from proxmox_mcp.tools.storage import get_available_isos

    mock_client.api_call.return_value = [
        {"volid": "local:iso/ubuntu.iso", "format": "iso", "size": 3 * 1024**3},
    ]

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await get_available_isos("pve1")

    assert result["status"] == "success"
    assert result["storage"] == "local"
    assert result["count"] == 1
    assert len(result["isos"]) == 1


@pytest.mark.asyncio
async def test_get_available_isos_custom_storage(mock_client):
    from proxmox_mcp.tools.storage import get_available_isos

    mock_client.api_call.return_value = []

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await get_available_isos("pve1", storage="nfs-share")

    assert result["status"] == "success"
    assert result["storage"] == "nfs-share"
    assert result["count"] == 0


# --- get_available_templates ---


@pytest.mark.asyncio
async def test_get_available_templates(mock_client):
    from proxmox_mcp.tools.storage import get_available_templates

    mock_client.api_call.return_value = [
        {
            "volid": "local:vztmpl/debian-12-standard_12.2-1_amd64.tar.zst",
            "format": "tgz",
            "size": 100 * 1024**2,
        },
        {
            "volid": "local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst",
            "format": "tgz",
            "size": 120 * 1024**2,
        },
    ]

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await get_available_templates("pve1")

    assert result["status"] == "success"
    assert result["storage"] == "local"
    assert result["count"] == 2
    assert len(result["templates"]) == 2


@pytest.mark.asyncio
async def test_get_available_templates_error(mock_client):
    from proxmox_mcp.tools.storage import get_available_templates

    mock_client.api_call.side_effect = Exception("storage offline")

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await get_available_templates("pve1")

    assert result["status"] == "error"


# --- download_to_storage ---


@pytest.mark.asyncio
async def test_download_to_storage(mock_client):
    from proxmox_mcp.tools.storage import download_to_storage

    mock_client.api_call.return_value = "UPID:pve1:00001:download"
    mock_client.is_dry_run = False

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await download_to_storage(
            node="pve1",
            storage="local",
            url="https://example.com/ubuntu.iso",
            content="iso",
            filename="ubuntu.iso",
        )

    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_download_to_storage_invalid_content(mock_client):
    from proxmox_mcp.tools.storage import download_to_storage

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await download_to_storage(
            node="pve1",
            storage="local",
            url="https://example.com/file.tar",
            content="backup",
            filename="file.tar",
        )

    assert result["status"] == "error"
    assert "iso" in result["message"]


@pytest.mark.asyncio
async def test_download_to_storage_dry_run(mock_client):
    from proxmox_mcp.tools.storage import download_to_storage

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await download_to_storage(
            node="pve1",
            storage="local",
            url="https://example.com/ubuntu.iso",
            content="iso",
            filename="ubuntu.iso",
        )

    assert result["status"] == "dry_run"


# ---------------------------------------------------------------------------
# Regression tests (phase 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_to_storage_rejects_bad_scheme(mock_client):
    from proxmox_mcp.tools.storage import download_to_storage

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await download_to_storage(
            node="pve1",
            storage="local",
            url="ftp://example.com/x.iso",
            content="iso",
            filename="x.iso",
        )
    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"
    mock_client.api_call.assert_not_called()


@pytest.mark.asyncio
async def test_download_to_storage_rejects_loopback(mock_client):
    from proxmox_mcp.tools.storage import download_to_storage

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await download_to_storage(
            node="pve1",
            storage="local",
            url="http://127.0.0.1/x.iso",
            content="iso",
            filename="x.iso",
        )
    assert result["status"] == "error"
    result = await download_to_storage(
        node="pve1",
        storage="local",
        url="http://169.254.169.254/latest/meta-data",
        content="iso",
        filename="x.iso",
    )
    assert result["status"] == "error"
    result = await download_to_storage(
        node="pve1",
        storage="local",
        url="http://[::1]/x.iso",
        content="iso",
        filename="x.iso",
    )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_download_to_storage_rejects_local_domain(mock_client):
    from proxmox_mcp.tools.storage import download_to_storage

    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        result = await download_to_storage(
            node="pve1",
            storage="local",
            url="http://intranet.local/x.iso",
            content="iso",
            filename="x.iso",
        )
    assert result["status"] == "error"
    assert result["error_type"] == "InvalidParameterError"


@pytest.mark.asyncio
async def test_download_to_storage_accepts_https(mock_client):
    from proxmox_mcp.tools.storage import download_to_storage

    mock_client.is_dry_run = False
    with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
        mock_client.api_call = AsyncMock(return_value="UPID:x")
        result = await download_to_storage(
            node="pve1",
            storage="local",
            url="https://example.com/x.iso",
            content="iso",
            filename="x.iso",
        )
    assert result["status"] == "submitted"
