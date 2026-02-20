from proxmox_mcp.utils.formatters import (
    format_vm_summary,
    format_container_summary,
    format_bytes,
    format_uptime,
    format_task_result,
)


def test_format_vm_summary():
    raw = {
        "vmid": 100, "name": "test-vm", "status": "running", "node": "pve1",
        "maxcpu": 4, "maxmem": 4294967296, "mem": 2147483648,
        "maxdisk": 34359738368, "uptime": 90061, "cpu": 0.156, "tags": "web;prod",
    }
    result = format_vm_summary(raw)
    assert result["vmid"] == 100
    assert result["name"] == "test-vm"
    assert result["type"] == "qemu"
    assert result["cpu_cores"] == 4
    assert result["memory_mb"] == 4096
    assert result["memory_used_mb"] == 2048
    assert result["disk_gb"] == 32
    assert result["cpu_usage_percent"] == 15.6
    assert result["tags"] == ["web", "prod"]


def test_format_container_summary():
    raw = {
        "vmid": 200, "name": "ct-test", "status": "stopped", "node": "pve2",
        "maxcpu": 2, "maxmem": 1073741824, "mem": 0, "maxdisk": 8589934592,
        "uptime": 0, "cpu": 0,
    }
    result = format_container_summary(raw)
    assert result["type"] == "lxc"
    assert result["memory_mb"] == 1024


def test_format_bytes():
    assert format_bytes(500) == "500.0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1073741824) == "1.0 GB"
    assert format_bytes(1099511627776) == "1.0 TB"


def test_format_uptime():
    assert format_uptime(0) == "0d 0h 0m"
    assert format_uptime(90061) == "1d 1h 1m"
    assert format_uptime(3661) == "0d 1h 1m"


def test_format_task_result():
    result = format_task_result({"data": "UPID:pve1:00001234:abcdef:12345678:vzdump:100:root@pam:"})
    assert result["status"] == "submitted"
    assert "UPID" in result["task_upid"]
