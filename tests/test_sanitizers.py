"""Tests for input sanitization and validation functions."""

import pytest

from proxmox_mcp.utils.errors import InvalidParameterError
from proxmox_mcp.utils.sanitizers import (
    check_shell_injection,
    validate_device_path,
    validate_filesystem,
    validate_label,
    validate_mkfs_options,
    validate_mount_options,
    validate_mount_path,
    validate_partition_table,
    validate_storage_id,
)


# --- check_shell_injection ---


class TestShellInjection:
    def test_clean_string_passes(self):
        check_shell_injection("hello-world_123", "test")

    @pytest.mark.parametrize(
        "bad_input",
        [
            "hello;world",
            "test|pipe",
            "test&bg",
            "$(whoami)",
            "test`cmd`",
            "test\\escape",
            "test'quote",
            'test"double',
            "test(paren)",
            "test{brace}",
            "test<angle>",
            "test!bang",
            "test~tilde",
            "test#hash",
            "test\nnewline",
            "test\rcarriage",
        ],
    )
    def test_rejects_shell_metacharacters(self, bad_input):
        with pytest.raises(InvalidParameterError, match="forbidden characters"):
            check_shell_injection(bad_input, "test_param")


# --- validate_device_path ---


class TestDevicePath:
    def test_valid_whole_disk(self):
        validate_device_path("/dev/sdb")
        validate_device_path("/dev/nvme0n1")
        validate_device_path("/dev/vda")

    def test_rejects_partition_when_not_allowed(self):
        with pytest.raises(InvalidParameterError, match="whole disk"):
            validate_device_path("/dev/sdb1")

    def test_allows_partition_when_flag_set(self):
        validate_device_path("/dev/sdb1", allow_partition=True)
        validate_device_path("/dev/nvme0n1p1", allow_partition=True)

    def test_rejects_mapper_paths(self):
        with pytest.raises(InvalidParameterError):
            validate_device_path("/dev/mapper/vg-lv")

    def test_rejects_relative_paths(self):
        with pytest.raises(InvalidParameterError):
            validate_device_path("sdb")

    def test_rejects_injection_in_device(self):
        with pytest.raises(InvalidParameterError):
            validate_device_path("/dev/sdb;rm -rf /")


# --- validate_mount_path ---


class TestMountPath:
    def test_valid_paths(self):
        validate_mount_path("/mnt/data")
        validate_mount_path("/srv/storage")
        validate_mount_path("/media/usb")
        validate_mount_path("/mnt/my-data/subdir")

    def test_rejects_root(self):
        with pytest.raises(InvalidParameterError):
            validate_mount_path("/")

    def test_rejects_etc(self):
        with pytest.raises(InvalidParameterError):
            validate_mount_path("/etc/something")

    def test_rejects_var(self):
        with pytest.raises(InvalidParameterError):
            validate_mount_path("/var/lib/data")

    def test_rejects_path_traversal(self):
        with pytest.raises(InvalidParameterError, match="path traversal"):
            validate_mount_path("/mnt/../../etc/passwd")

    def test_rejects_home(self):
        with pytest.raises(InvalidParameterError):
            validate_mount_path("/home/user/data")

    def test_rejects_injection(self):
        with pytest.raises(InvalidParameterError):
            validate_mount_path("/mnt/data;rm -rf /")


# --- validate_storage_id ---


class TestStorageId:
    def test_valid_ids(self):
        validate_storage_id("local-data")
        validate_storage_id("ssd_vms")
        validate_storage_id("backup1")
        validate_storage_id("a")

    def test_rejects_starting_with_number(self):
        with pytest.raises(InvalidParameterError):
            validate_storage_id("1storage")

    def test_rejects_special_chars(self):
        with pytest.raises(InvalidParameterError):
            validate_storage_id("my storage")

    def test_rejects_injection(self):
        with pytest.raises(InvalidParameterError):
            validate_storage_id("test;drop")


# --- validate_label ---


class TestLabel:
    def test_valid_labels(self):
        validate_label("data")
        validate_label("vm-storage")
        validate_label("BOOT_EFI")

    def test_rejects_too_long(self):
        with pytest.raises(InvalidParameterError):
            validate_label("a" * 17)

    def test_rejects_special_chars(self):
        with pytest.raises(InvalidParameterError):
            validate_label("my label")


# --- validate_mount_options ---


class TestMountOptions:
    def test_valid_options(self):
        validate_mount_options("defaults")
        validate_mount_options("defaults,noatime")
        validate_mount_options("rw,nosuid,nodev")
        validate_mount_options("commit=30")

    def test_rejects_unknown_option(self):
        with pytest.raises(InvalidParameterError, match="not allowed"):
            validate_mount_options("defaults,exec_shell")

    def test_rejects_injection(self):
        with pytest.raises(InvalidParameterError):
            validate_mount_options("defaults;rm -rf /")


# --- validate_mkfs_options ---


class TestMkfsOptions:
    def test_valid_options(self):
        validate_mkfs_options("-m 1")
        validate_mkfs_options("-L mydata")

    def test_rejects_unknown_flag(self):
        with pytest.raises(InvalidParameterError):
            validate_mkfs_options("-Z evil")

    def test_rejects_injection(self):
        with pytest.raises(InvalidParameterError):
            validate_mkfs_options("-m 1; rm -rf /")


# --- validate_filesystem ---


class TestFilesystem:
    def test_valid_filesystems(self):
        validate_filesystem("ext4")
        validate_filesystem("xfs")
        validate_filesystem("vfat")

    def test_rejects_invalid(self):
        with pytest.raises(InvalidParameterError):
            validate_filesystem("ntfs")


# --- validate_partition_table ---


class TestPartitionTable:
    def test_valid_types(self):
        validate_partition_table("gpt")
        validate_partition_table("msdos")

    def test_rejects_invalid(self):
        with pytest.raises(InvalidParameterError):
            validate_partition_table("mbr")
