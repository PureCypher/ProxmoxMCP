"""Tests for MCP prompt templates."""

from proxmox_mcp.prompts.prompts import (
    capacity_planning,
    disaster_recovery_check,
    infrastructure_overview,
    security_audit,
    troubleshoot_vm,
    vm_deployment,
)


def test_infrastructure_overview():
    result = infrastructure_overview()
    assert isinstance(result, str)
    assert "cluster" in result.lower()
    assert "node" in result.lower()
    assert "storage" in result.lower()


def test_capacity_planning():
    result = capacity_planning()
    assert isinstance(result, str)
    assert "capacity" in result.lower()
    assert "cpu" in result.lower()
    assert "ram" in result.lower()


def test_vm_deployment_defaults():
    result = vm_deployment(name="web-server", purpose="web hosting")
    assert isinstance(result, str)
    assert "web-server" in result
    assert "web hosting" in result
    assert "linux" in result


def test_vm_deployment_custom_os():
    result = vm_deployment(name="win-dc", purpose="domain controller", os="windows")
    assert isinstance(result, str)
    assert "win-dc" in result
    assert "windows" in result


def test_disaster_recovery_check():
    result = disaster_recovery_check()
    assert isinstance(result, str)
    assert "backup" in result.lower()
    assert "snapshot" in result.lower()


def test_security_audit():
    result = security_audit()
    assert isinstance(result, str)
    assert "firewall" in result.lower()
    assert "security" in result.lower()


def test_troubleshoot_vm():
    result = troubleshoot_vm(vmid=100)
    assert isinstance(result, str)
    assert "100" in result
    assert "status" in result.lower()
