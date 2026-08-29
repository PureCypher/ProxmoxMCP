"""Tests for physical disk management tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxmox_mcp.ssh import SSHResult


@pytest.fixture
def mock_client():
    """Create a mock ProxmoxClient."""
    client = MagicMock()
    client.api_call = AsyncMock()
    client.validate_node = MagicMock()
    client.is_dry_run = False
    return client


@pytest.fixture
def mock_ssh():
    """Create a mock SSHExecutor."""
    ssh = MagicMock()
    ssh.execute = AsyncMock()
    return ssh


# ---------------------------------------------------------------------------
# list_physical_disks
# ---------------------------------------------------------------------------


class TestListPhysicalDisks:
    @pytest.mark.asyncio
    async def test_list_disks_success(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import list_physical_disks

        mock_client.api_call.return_value = [
            {
                "devpath": "/dev/sda",
                "model": "Samsung SSD 870",
                "serial": "S5XXNJ0R123456",
                "size": 500107862016,
                "type": "sata",
                "rpm": 0,
                "health": "PASSED",
                "gpt": 1,
                "used": "LVM",
            },
            {
                "devpath": "/dev/sdb",
                "model": "WD Red 10TB",
                "serial": "WD-WMC1T0123456",
                "size": 10000831348736,
                "type": "sata",
                "rpm": 5400,
                "health": "PASSED",
                "gpt": 0,
                "used": "",
            },
        ]

        # SSH lsblk returns empty (no enrichment needed for basic test)
        mock_ssh.execute.return_value = SSHResult(
            exit_code=0, stdout='{"blockdevices": []}', stderr=""
        )

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await list_physical_disks("pve1")

        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["disks"][0]["device"] == "/dev/sda"
        assert result["disks"][0]["in_use"] is True
        assert result["disks"][1]["device"] == "/dev/sdb"
        assert result["disks"][1]["in_use"] is False

    @pytest.mark.asyncio
    async def test_list_disks_filter_unused(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import list_physical_disks

        mock_client.api_call.return_value = [
            {"devpath": "/dev/sda", "size": 500000, "used": "LVM"},
            {"devpath": "/dev/sdb", "size": 10000000, "used": ""},
        ]
        mock_ssh.execute.return_value = SSHResult(
            exit_code=0, stdout='{"blockdevices": []}', stderr=""
        )

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await list_physical_disks("pve1", filter_unused=True)

        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["disks"][0]["device"] == "/dev/sdb"

    @pytest.mark.asyncio
    async def test_list_disks_invalid_node(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import list_physical_disks

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await list_physical_disks("")

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_list_disks_api_error(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import list_physical_disks

        mock_client.api_call.side_effect = Exception("API unreachable")

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await list_physical_disks("pve1")

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# partition_disk — safety gates
# ---------------------------------------------------------------------------


class TestPartitionDisk:
    @pytest.mark.asyncio
    async def test_requires_confirm(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import partition_disk

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await partition_disk("pve1", "/dev/sdb", confirm_destructive=False)

        assert result["status"] == "confirmation_required"
        assert "DESTROY" in result["warning"]

    @pytest.mark.asyncio
    async def test_rejects_partition_path(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import partition_disk

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await partition_disk("pve1", "/dev/sdb1", confirm_destructive=True)

        assert result["status"] == "error"
        assert "whole disk" in result["message"] or "invalid" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_rejects_boot_disk(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import partition_disk

        # Device exists
        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(exit_code=0, stdout="/\n/boot\n", stderr=""),  # lsblk mounts
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await partition_disk("pve1", "/dev/sda", confirm_destructive=True)

        assert result["status"] == "error"
        assert "boot" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_rejects_mounted_device(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import partition_disk

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(exit_code=0, stdout="", stderr=""),  # lsblk mounts (no boot)
            SSHResult(  # findmnt shows mounted
                exit_code=0,
                stdout="/dev/sdb1 /mnt/data",
                stderr="",
            ),
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await partition_disk("pve1", "/dev/sdb", confirm_destructive=True)

        assert result["status"] == "error"
        assert "mounted" in result["message"].lower() or "in use" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_rejects_device_not_found(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import partition_disk

        mock_ssh.execute.return_value = SSHResult(exit_code=1, stdout="", stderr="not found")

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await partition_disk("pve1", "/dev/sdz", confirm_destructive=True)

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_rejects_shell_injection(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import partition_disk

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await partition_disk("pve1", "/dev/sdb;rm -rf /", confirm_destructive=True)

        assert result["status"] == "error"
        assert "forbidden" in result["message"].lower() or "invalid" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_dry_run(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import partition_disk

        mock_client.is_dry_run = True
        mock_client.dry_run_response.return_value = {
            "status": "dry_run",
            "action": "partition_disk",
        }

        # Pass all safety gates
        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(exit_code=0, stdout="", stderr=""),  # lsblk mounts
            SSHResult(exit_code=1, stdout="", stderr=""),  # findmnt (not mounted)
            SSHResult(exit_code=0, stdout="---END---", stderr=""),  # LVM/ZFS/MD combined (none)
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await partition_disk("pve1", "/dev/sdb", confirm_destructive=True)

        assert result["status"] == "dry_run"

    @pytest.mark.asyncio
    async def test_success(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import partition_disk

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(exit_code=0, stdout="", stderr=""),  # lsblk mounts
            SSHResult(exit_code=1, stdout="", stderr=""),  # findmnt
            SSHResult(exit_code=0, stdout="---END---", stderr=""),  # LVM/ZFS/MD combined (none)
            SSHResult(exit_code=0, stdout="", stderr=""),  # wipefs
            SSHResult(exit_code=0, stdout="", stderr=""),  # sgdisk (GPT + partition)
            SSHResult(exit_code=0, stdout="", stderr=""),  # blockdev --rereadpt
            SSHResult(exit_code=0, stdout="", stderr=""),  # mkfs.ext4
            SSHResult(  # blkid
                exit_code=0,
                stdout="UUID=12345678-1234-1234-1234-123456789abc\nTYPE=ext4\n",
                stderr="",
            ),
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await partition_disk(
                "pve1",
                "/dev/sdb",
                filesystem="ext4",
                label="data",
                confirm_destructive=True,
            )

        assert result["status"] == "success"
        assert result["partition_table"] == "gpt"
        assert result["partitions_created"][0]["device"] == "/dev/sdb1"
        assert result["partitions_created"][0]["uuid"] == "12345678-1234-1234-1234-123456789abc"


# ---------------------------------------------------------------------------
# format_disk — safety gates
# ---------------------------------------------------------------------------


class TestFormatDisk:
    @pytest.mark.asyncio
    async def test_requires_confirm(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import format_disk

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await format_disk("pve1", "/dev/sdb1", "ext4", confirm_destructive=False)

        assert result["status"] == "confirmation_required"

    @pytest.mark.asyncio
    async def test_rejects_mounted_partition(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import format_disk

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(exit_code=0, stdout="/mnt/data", stderr=""),  # findmnt
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await format_disk("pve1", "/dev/sdb1", "ext4", confirm_destructive=True)

        assert result["status"] == "error"
        assert "mounted" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_success(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import format_disk

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(exit_code=1, stdout="", stderr=""),  # findmnt (not mounted)
            SSHResult(exit_code=0, stdout="", stderr=""),  # wipefs
            SSHResult(exit_code=0, stdout="", stderr=""),  # mkfs
            SSHResult(  # blkid
                exit_code=0,
                stdout="UUID=abcd-ef01\nTYPE=ext4\n",
                stderr="",
            ),
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await format_disk(
                "pve1",
                "/dev/sdb1",
                "ext4",
                label="data",
                confirm_destructive=True,
            )

        assert result["status"] == "success"
        assert result["filesystem"] == "ext4"
        assert result["uuid"] == "abcd-ef01"

    @pytest.mark.asyncio
    async def test_rejects_invalid_filesystem(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import format_disk

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await format_disk("pve1", "/dev/sdb1", "ntfs", confirm_destructive=True)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_rejects_injection_in_options(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import format_disk

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await format_disk(
                "pve1",
                "/dev/sdb1",
                "ext4",
                options="; rm -rf /",
                confirm_destructive=True,
            )

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# create_mount_point
# ---------------------------------------------------------------------------


class TestCreateMountPoint:
    @pytest.mark.asyncio
    async def test_success(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import create_mount_point

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(  # blkid
                exit_code=0,
                stdout="TYPE=ext4\nUUID=12345678-abcd-1234-abcd-123456789abc\n",
                stderr="",
            ),
            SSHResult(exit_code=1, stdout="", stderr=""),  # findmnt (not mounted)
            SSHResult(exit_code=0, stdout="", stderr=""),  # mkdir
            SSHResult(exit_code=0, stdout="", stderr=""),  # mount
            SSHResult(exit_code=0, stdout="/dev/sdb1", stderr=""),  # findmnt verify
            SSHResult(exit_code=0, stdout="", stderr=""),  # cp fstab backup
            SSHResult(exit_code=0, stdout="", stderr=""),  # echo >> fstab
            SSHResult(exit_code=0, stdout="", stderr=""),  # mount -a --fake
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await create_mount_point("pve1", "/dev/sdb1", "/mnt/data")

        assert result["status"] == "success"
        assert result["mount_path"] == "/mnt/data"
        assert result["fstab_entry_added"] is True

    @pytest.mark.asyncio
    async def test_rejects_invalid_mount_path(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import create_mount_point

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await create_mount_point("pve1", "/dev/sdb1", "/etc/data")

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import create_mount_point

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await create_mount_point("pve1", "/dev/sdb1", "/mnt/../../etc/passwd")

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_rejects_already_mounted(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import create_mount_point

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(  # blkid
                exit_code=0,
                stdout="TYPE=ext4\nUUID=aabbccdd-1122-3344-5566-778899aabbcc\n",
                stderr="",
            ),
            SSHResult(exit_code=0, stdout="/mnt/data", stderr=""),  # findmnt (already mounted!)
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await create_mount_point("pve1", "/dev/sdb1", "/mnt/data")

        assert result["status"] == "error"
        assert "already" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_fstab_rollback_on_validation_failure(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import create_mount_point

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="exists", stderr=""),  # test -b
            SSHResult(  # blkid
                exit_code=0,
                stdout="TYPE=ext4\nUUID=aabbccdd-1122-3344-5566-778899aabbcc\n",
                stderr="",
            ),
            SSHResult(exit_code=1, stdout="", stderr=""),  # findmnt (not mounted)
            SSHResult(exit_code=0, stdout="", stderr=""),  # mkdir
            SSHResult(exit_code=0, stdout="", stderr=""),  # mount
            SSHResult(exit_code=0, stdout="/dev/sdb1", stderr=""),  # findmnt verify
            SSHResult(exit_code=0, stdout="", stderr=""),  # cp fstab backup
            SSHResult(exit_code=0, stdout="", stderr=""),  # echo >> fstab
            SSHResult(exit_code=1, stdout="", stderr="parse error"),  # mount -a --fake FAILS
            SSHResult(exit_code=0, stdout="", stderr=""),  # cp fstab rollback
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await create_mount_point("pve1", "/dev/sdb1", "/mnt/data")

        assert result["status"] == "success"
        # fstab entry should NOT have been added due to rollback
        assert result["fstab_entry_added"] is False


# ---------------------------------------------------------------------------
# unmount_path
# ---------------------------------------------------------------------------


class TestUnmountPath:
    @pytest.mark.asyncio
    async def test_success(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import unmount_path

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="/dev/sdb1", stderr=""),  # findmnt (is mounted)
            SSHResult(exit_code=0, stdout="", stderr=""),  # umount
        ]

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await unmount_path("pve1", "/mnt/data")

        assert result["status"] == "success"
        assert result["unmounted"] is True

    @pytest.mark.asyncio
    async def test_rejects_not_mounted(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import unmount_path

        mock_ssh.execute.return_value = SSHResult(exit_code=1, stdout="", stderr="")

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await unmount_path("pve1", "/mnt/data")

        assert result["status"] == "error"
        assert "not currently mounted" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_rejects_critical_path(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import unmount_path

        with (
            patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
        ):
            result = await unmount_path("pve1", "/etc/data")

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# add_storage / remove_storage
# ---------------------------------------------------------------------------


class TestAddStorage:
    @pytest.mark.asyncio
    async def test_add_dir_storage_success(self, mock_client):
        from proxmox_mcp.tools.storage import add_storage

        mock_client.api_call.side_effect = [
            [],  # GET /storage (no existing)
            None,  # POST /storage
        ]

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await add_storage(
                storage_id="data",
                storage_type="dir",
                content="images,iso,vztmpl",
                path="/mnt/data",
                nodes="pve1",
            )

        assert result["status"] == "success"
        assert result["storage_id"] == "data"
        assert "images" in result["content"]
        assert "iso" in result["content"]

    @pytest.mark.asyncio
    async def test_add_storage_duplicate_id(self, mock_client):
        from proxmox_mcp.tools.storage import add_storage

        mock_client.api_call.return_value = [
            {"storage": "data", "type": "dir"},
        ]

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await add_storage(
                storage_id="data",
                storage_type="dir",
                content="images",
                path="/mnt/data",
            )

        assert result["status"] == "error"
        assert "already exists" in result["message"]

    @pytest.mark.asyncio
    async def test_add_storage_invalid_type(self, mock_client):
        from proxmox_mcp.tools.storage import add_storage

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await add_storage(
                storage_id="test",
                storage_type="invalid",
                content="images",
            )

        assert result["status"] == "error"
        assert "Invalid storage type" in result["message"]

    @pytest.mark.asyncio
    async def test_add_storage_invalid_content(self, mock_client):
        from proxmox_mcp.tools.storage import add_storage

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await add_storage(
                storage_id="test",
                storage_type="dir",
                content="images,bogus",
                path="/mnt/test",
            )

        assert result["status"] == "error"
        assert "Invalid content" in result["message"]

    @pytest.mark.asyncio
    async def test_add_nfs_requires_server_and_export(self, mock_client):
        from proxmox_mcp.tools.storage import add_storage

        mock_client.api_call.return_value = []  # no existing storage

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await add_storage(
                storage_id="nfs1",
                storage_type="nfs",
                content="backup",
            )

        assert result["status"] == "error"
        assert "server" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_add_storage_dry_run(self, mock_client):
        from proxmox_mcp.tools.storage import add_storage

        mock_client.is_dry_run = True
        mock_client.api_call.return_value = []
        mock_client.dry_run_response.return_value = {"status": "dry_run"}

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await add_storage(
                storage_id="test",
                storage_type="dir",
                content="images",
                path="/mnt/test",
            )

        assert result["status"] == "dry_run"


class TestRemoveStorage:
    @pytest.mark.asyncio
    async def test_requires_confirm(self, mock_client):
        from proxmox_mcp.tools.storage import remove_storage

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await remove_storage("my-storage", confirm=False)

        assert result["status"] == "confirmation_required"

    @pytest.mark.asyncio
    async def test_rejects_default_storage(self, mock_client):
        from proxmox_mcp.tools.storage import remove_storage

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await remove_storage("local", confirm=True)

        assert result["status"] == "error"
        assert "default" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_rejects_local_lvm(self, mock_client):
        from proxmox_mcp.tools.storage import remove_storage

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await remove_storage("local-lvm", confirm=True)

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_success(self, mock_client):
        from proxmox_mcp.tools.storage import remove_storage

        mock_client.api_call.return_value = None

        with patch("proxmox_mcp.tools.storage.get_client", return_value=mock_client):
            result = await remove_storage("my-data", confirm=True)

        assert result["status"] == "success"
        assert "my-data" in result["message"]
