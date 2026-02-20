import pytest
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name
from proxmox_mcp.utils.errors import InvalidParameterError


def test_validate_vmid_valid():
    validate_vmid(100)
    validate_vmid(999999999)


def test_validate_vmid_invalid():
    with pytest.raises(InvalidParameterError):
        validate_vmid(0)
    with pytest.raises(InvalidParameterError):
        validate_vmid(-1)
    with pytest.raises(InvalidParameterError):
        validate_vmid(99)


def test_validate_node_name_valid():
    validate_node_name("pve1")
    validate_node_name("node-01")


def test_validate_node_name_invalid():
    with pytest.raises(InvalidParameterError):
        validate_node_name("")
    with pytest.raises(InvalidParameterError):
        validate_node_name("node with spaces")
