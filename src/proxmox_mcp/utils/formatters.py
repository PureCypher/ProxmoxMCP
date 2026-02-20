"""Response formatting helpers for consistent tool output."""


def format_vm_summary(vm_data: dict) -> dict:
    """Standard VM summary format."""
    return {
        "vmid": vm_data.get("vmid"),
        "name": vm_data.get("name", "unnamed"),
        "status": vm_data.get("status"),
        "node": vm_data.get("node"),
        "type": "qemu",
        "cpu_cores": vm_data.get("maxcpu", 0),
        "memory_mb": vm_data.get("maxmem", 0) // (1024 * 1024),
        "memory_used_mb": vm_data.get("mem", 0) // (1024 * 1024),
        "disk_gb": vm_data.get("maxdisk", 0) // (1024**3),
        "uptime_seconds": vm_data.get("uptime", 0),
        "cpu_usage_percent": round(vm_data.get("cpu", 0) * 100, 2),
        "tags": vm_data.get("tags", "").split(";") if vm_data.get("tags") else [],
    }


def format_container_summary(ct_data: dict) -> dict:
    """Standard container summary format."""
    return {
        "vmid": ct_data.get("vmid"),
        "name": ct_data.get("name", "unnamed"),
        "status": ct_data.get("status"),
        "node": ct_data.get("node"),
        "type": "lxc",
        "cpu_cores": ct_data.get("maxcpu", 0),
        "memory_mb": ct_data.get("maxmem", 0) // (1024 * 1024),
        "memory_used_mb": ct_data.get("mem", 0) // (1024 * 1024),
        "disk_gb": ct_data.get("maxdisk", 0) // (1024**3),
        "uptime_seconds": ct_data.get("uptime", 0),
        "cpu_usage_percent": round(ct_data.get("cpu", 0) * 100, 2),
        "tags": ct_data.get("tags", "").split(";") if ct_data.get("tags") else [],
    }


def format_bytes(bytes_val: int) -> str:
    """Human-readable byte formatting."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def format_uptime(seconds: int) -> str:
    """Human-readable uptime."""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m"


def format_task_result(task_data: dict) -> dict:
    """Standard task result format including UPID for tracking."""
    return {
        "task_upid": task_data.get("upid") or task_data.get("data"),
        "status": "submitted",
        "message": "Task submitted successfully. Use get_task_status with the UPID to track progress.",
    }
