"""SSH tools for direct command execution on Proxmox VMs and containers.

Provides curated, high-level tools for package installation, service management,
file transfer, script execution, and system information retrieval. Supports
auto-discovery of VM/CT IP addresses via QEMU guest agent or LXC interfaces.
"""

import base64
import logging

from proxmox_mcp.utils.errors import (
    InvalidParameterError,
    SSHExecutionError,
    format_error_response,
)
from proxmox_mcp.utils.sanitizers import (
    check_shell_injection,
    validate_package_name,
    validate_remote_file_path,
    validate_script_interpreter,
    validate_service_action,
    validate_service_name,
)
from proxmox_mcp.utils.validators import validate_vmid

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp

    return mcp


def get_ssh():
    from proxmox_mcp.server import ssh_executor

    return ssh_executor


mcp = get_mcp()


# ---------------------------------------------------------------------------
# IP auto-discovery helpers
# ---------------------------------------------------------------------------


async def _resolve_vm_ip(client, vmid: int, node: str) -> str:
    """Auto-discover a VM's IP address via QEMU guest agent or LXC interfaces.

    Tries QEMU guest agent first, then LXC interfaces API. Filters out
    loopback and link-local addresses, preferring IPv4.

    Returns:
        The best available IP address for SSH connection.

    Raises:
        SSHExecutionError: If no usable IP address is found.
    """
    interfaces = []

    # Try QEMU guest agent
    try:
        data = await client.api_call(
            client.api.nodes(node).qemu(vmid).agent("network-get-interfaces").get
        )
        raw = data.get("result", data)
        if isinstance(raw, list):
            interfaces = raw
    except Exception:
        pass

    # Try LXC interfaces
    if not interfaces:
        try:
            data = await client.api_call(
                client.api.nodes(node).lxc(vmid).interfaces.get
            )
            if isinstance(data, list):
                interfaces = data
        except Exception:
            pass

    if not interfaces:
        raise SSHExecutionError(
            f"Cannot discover IP for VMID {vmid}. "
            "Ensure the VM/CT is running and has QEMU guest agent (VMs) "
            "or network configured (CTs)."
        )

    # Extract usable IPs: prefer IPv4, skip loopback and link-local
    ipv4_candidates = []
    ipv6_candidates = []

    for iface in interfaces:
        iface_name = iface.get("name", "")
        if iface_name == "lo":
            continue

        # QEMU agent format: ip-addresses list
        for addr_info in iface.get("ip-addresses", []):
            ip = addr_info.get("ip-address", "")
            ip_type = addr_info.get("ip-address-type", "")
            if ip_type == "ipv4" and not ip.startswith("127.") and not ip.startswith("169.254."):
                ipv4_candidates.append(ip)
            elif ip_type == "ipv6" and not ip.startswith("fe80:") and ip != "::1":
                ipv6_candidates.append(ip)

        # LXC format: inet/inet6 fields (CIDR notation)
        inet = iface.get("inet", "")
        if inet:
            ip = inet.split("/")[0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                ipv4_candidates.append(ip)
        inet6 = iface.get("inet6", "")
        if inet6:
            ip = inet6.split("/")[0]
            if not ip.startswith("fe80:") and ip != "::1":
                ipv6_candidates.append(ip)

        # LXC format: hwaddr with ip (some proxmox versions)
        ip_field = iface.get("ip", "")
        if ip_field:
            ip = ip_field.split("/")[0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                ipv4_candidates.append(ip)

    best_ip = next(iter(ipv4_candidates), None) or next(iter(ipv6_candidates), None)
    if not best_ip:
        raise SSHExecutionError(
            f"No usable IP address found for VMID {vmid}. "
            f"Interfaces found but all addresses are loopback or link-local."
        )

    logger.info("Resolved VMID %d to IP %s", vmid, best_ip)
    return best_ip


async def _get_ssh_target(
    vmid: int,
    node: str | None = None,
    target_ip: str | None = None,
) -> tuple[str, str]:
    """Resolve the SSH target IP and node for a VMID.

    Args:
        vmid: The VM/CT ID.
        node: Node name override.
        target_ip: Direct IP override (skips auto-discovery).

    Returns:
        Tuple of (ip_address, node_name).
    """
    client = get_client()
    validate_vmid(vmid)
    resolved_node = await client.resolve_node(vmid, node)

    if target_ip:
        check_shell_injection(target_ip, "target_ip")
        return target_ip, resolved_node

    ip = await _resolve_vm_ip(client, vmid, resolved_node)
    return ip, resolved_node


def _build_ssh_overrides(
    ssh_user: str | None,
    ssh_password: str | None,
    ssh_key_path: str | None,
    ssh_port: int | None,
) -> dict:
    """Build SSH credential override kwargs."""
    overrides: dict = {}
    if ssh_user:
        check_shell_injection(ssh_user, "ssh_user")
        overrides["username"] = ssh_user
    if ssh_password:
        overrides["password"] = ssh_password
    if ssh_key_path:
        check_shell_injection(ssh_key_path, "ssh_key_path")
        overrides["key_path"] = ssh_key_path
    if ssh_port is not None:
        overrides["port"] = ssh_port
    return overrides


# ---------------------------------------------------------------------------
# Package manager detection
# ---------------------------------------------------------------------------


async def _detect_package_manager(ssh, host: str, **ssh_kwargs) -> str:
    """Detect the package manager on a remote host.

    Returns one of: apt, dnf, yum, apk, zypper, pacman.
    """
    managers = [
        ("apt-get", "apt"),
        ("dnf", "dnf"),
        ("yum", "yum"),
        ("apk", "apk"),
        ("zypper", "zypper"),
        ("pacman", "pacman"),
    ]
    for binary, name in managers:
        result = await ssh.execute_on_host(
            host, f"command -v {binary} >/dev/null 2>&1 && echo found", timeout=10, **ssh_kwargs
        )
        if result.success and "found" in result.stdout:
            return name

    raise SSHExecutionError("No supported package manager found on target system.")


def _build_install_command(manager: str, packages: list[str]) -> str:
    """Build the install command for a given package manager."""
    pkg_str = " ".join(packages)
    commands = {
        "apt": (
            f"DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
            f"apt-get install -y -qq {pkg_str}"
        ),
        "dnf": f"dnf install -y {pkg_str}",
        "yum": f"yum install -y {pkg_str}",
        "apk": f"apk add --no-cache {pkg_str}",
        "zypper": f"zypper install -y {pkg_str}",
        "pacman": f"pacman -Sy --noconfirm {pkg_str}",
    }
    return commands[manager]


def _build_remove_command(manager: str, packages: list[str]) -> str:
    """Build the remove command for a given package manager."""
    pkg_str = " ".join(packages)
    commands = {
        "apt": f"apt-get remove -y -qq {pkg_str}",
        "dnf": f"dnf remove -y {pkg_str}",
        "yum": f"yum remove -y {pkg_str}",
        "apk": f"apk del {pkg_str}",
        "zypper": f"zypper remove -y {pkg_str}",
        "pacman": f"pacman -R --noconfirm {pkg_str}",
    }
    return commands[manager]


# ---------------------------------------------------------------------------
# Tool 1: install_package
# ---------------------------------------------------------------------------


@mcp.tool()
async def install_package(
    vmid: int,
    packages: list[str],
    action: str = "install",
    node: str | None = None,
    target_ip: str | None = None,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    ssh_key_path: str | None = None,
    ssh_port: int | None = None,
) -> dict:
    """Install or remove packages on a VM or container via SSH.

    Auto-detects the package manager (apt, dnf, yum, apk, zypper, pacman).

    Args:
        vmid: The VM/CT ID to connect to.
        packages: List of package names to install or remove.
        action: 'install' or 'remove'.
        node: Node name override. Auto-detected if omitted.
        target_ip: Direct IP/hostname of the VM. Skips auto-discovery if provided.
        ssh_user: SSH username override (defaults to global config).
        ssh_password: SSH password override (defaults to global config).
        ssh_key_path: SSH private key path override (defaults to global config).
        ssh_port: SSH port override (defaults to global config).
    """
    try:
        if not packages:
            raise InvalidParameterError("At least one package name is required.")
        if action not in ("install", "remove"):
            raise InvalidParameterError("Action must be 'install' or 'remove'.")

        for pkg in packages:
            validate_package_name(pkg)

        ip, resolved_node = await _get_ssh_target(vmid, node, target_ip)
        ssh_kwargs = _build_ssh_overrides(ssh_user, ssh_password, ssh_key_path, ssh_port)
        ssh = get_ssh()

        # Detect package manager
        manager = await _detect_package_manager(ssh, ip, **ssh_kwargs)
        logger.info(
            "Detected package manager '%s' on VMID %d (%s)", manager, vmid, ip
        )

        # Build and execute command
        if action == "install":
            command = _build_install_command(manager, packages)
        else:
            command = _build_remove_command(manager, packages)

        result = await ssh.execute_on_host(ip, command, timeout=120, **ssh_kwargs)

        if not result.success:
            return {
                "status": "error",
                "vmid": vmid,
                "node": resolved_node,
                "target_ip": ip,
                "action": action,
                "packages": packages,
                "package_manager": manager,
                "exit_code": result.exit_code,
                "error": result.stderr[-500:] if result.stderr else "Unknown error",
            }

        return {
            "status": "success",
            "vmid": vmid,
            "node": resolved_node,
            "target_ip": ip,
            "action": action,
            "packages": packages,
            "package_manager": manager,
            "output": result.stdout[-1000:] if result.stdout else "",
        }
    except Exception as e:
        logger.error("Failed to %s packages on VMID %d: %s", action, vmid, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Tool 2: manage_service
# ---------------------------------------------------------------------------


@mcp.tool()
async def manage_service(
    vmid: int,
    service: str,
    action: str,
    node: str | None = None,
    target_ip: str | None = None,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    ssh_key_path: str | None = None,
    ssh_port: int | None = None,
) -> dict:
    """Manage a systemd service on a VM or container via SSH.

    Args:
        vmid: The VM/CT ID to connect to.
        service: Systemd service name (e.g., 'nginx', 'docker').
        action: Service action: 'start', 'stop', 'restart', 'reload', 'enable', 'disable', 'status'.
        node: Node name override. Auto-detected if omitted.
        target_ip: Direct IP/hostname of the VM. Skips auto-discovery if provided.
        ssh_user: SSH username override (defaults to global config).
        ssh_password: SSH password override (defaults to global config).
        ssh_key_path: SSH private key path override (defaults to global config).
        ssh_port: SSH port override (defaults to global config).
    """
    try:
        validate_service_name(service)
        validate_service_action(action)

        ip, resolved_node = await _get_ssh_target(vmid, node, target_ip)
        ssh_kwargs = _build_ssh_overrides(ssh_user, ssh_password, ssh_key_path, ssh_port)
        ssh = get_ssh()

        command = f"systemctl {action} {service}"
        # For status, also get detailed info
        if action == "status":
            command = (
                f"systemctl is-active {service} 2>/dev/null; "
                f"systemctl is-enabled {service} 2>/dev/null; "
                f"systemctl status {service} --no-pager -l 2>/dev/null"
            )

        result = await ssh.execute_on_host(ip, command, timeout=30, **ssh_kwargs)

        if action == "status":
            # Parse status output
            lines = result.stdout.strip().splitlines()
            is_active = lines[0].strip() if len(lines) > 0 else "unknown"
            is_enabled = lines[1].strip() if len(lines) > 1 else "unknown"
            full_status = "\n".join(lines[2:]) if len(lines) > 2 else ""
            return {
                "status": "success",
                "vmid": vmid,
                "node": resolved_node,
                "target_ip": ip,
                "service": service,
                "is_active": is_active,
                "is_enabled": is_enabled,
                "details": full_status[-1000:],
            }

        if not result.success:
            return {
                "status": "error",
                "vmid": vmid,
                "node": resolved_node,
                "target_ip": ip,
                "service": service,
                "action": action,
                "exit_code": result.exit_code,
                "error": result.stderr[-500:] if result.stderr else "Unknown error",
            }

        return {
            "status": "success",
            "vmid": vmid,
            "node": resolved_node,
            "target_ip": ip,
            "service": service,
            "action": action,
            "output": result.stdout[-500:] if result.stdout else "",
        }
    except Exception as e:
        logger.error("Failed to %s service '%s' on VMID %d: %s", action, service, vmid, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Tool 3: transfer_file
# ---------------------------------------------------------------------------


@mcp.tool()
async def transfer_file(
    vmid: int,
    content: str,
    destination: str,
    permissions: str = "0644",
    owner: str | None = None,
    node: str | None = None,
    target_ip: str | None = None,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    ssh_key_path: str | None = None,
    ssh_port: int | None = None,
) -> dict:
    """Upload file content to a VM or container via SSH.

    Writes the provided text content to a file on the target system.
    Uses base64 encoding for safe transfer of arbitrary content.

    Args:
        vmid: The VM/CT ID to connect to.
        content: The file content to write.
        destination: Absolute path on the target (e.g., '/etc/nginx/nginx.conf').
        permissions: File permissions in octal (e.g., '0644', '0755').
        owner: File owner in 'user:group' format (e.g., 'www-data:www-data').
        node: Node name override. Auto-detected if omitted.
        target_ip: Direct IP/hostname of the VM. Skips auto-discovery if provided.
        ssh_user: SSH username override (defaults to global config).
        ssh_password: SSH password override (defaults to global config).
        ssh_key_path: SSH private key path override (defaults to global config).
        ssh_port: SSH port override (defaults to global config).
    """
    try:
        validate_remote_file_path(destination)

        # Validate permissions format
        if not _is_valid_permissions(permissions):
            raise InvalidParameterError(
                f"Permissions '{permissions}' are invalid. Use octal format like '0644' or '0755'."
            )

        if owner:
            check_shell_injection(owner, "owner")

        ip, resolved_node = await _get_ssh_target(vmid, node, target_ip)
        ssh_kwargs = _build_ssh_overrides(ssh_user, ssh_password, ssh_key_path, ssh_port)
        ssh = get_ssh()

        # Base64 encode content for safe transfer
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

        # Ensure parent directory exists, write file, set permissions
        parent_dir = "/".join(destination.rsplit("/", 1)[:-1]) or "/"
        commands = [
            f"mkdir -p {parent_dir}",
            f"echo '{encoded}' | base64 -d > {destination}",
            f"chmod {permissions} {destination}",
        ]
        if owner:
            commands.append(f"chown {owner} {destination}")

        command = " && ".join(commands)
        result = await ssh.execute_on_host(ip, command, timeout=30, **ssh_kwargs)

        if not result.success:
            return {
                "status": "error",
                "vmid": vmid,
                "node": resolved_node,
                "target_ip": ip,
                "destination": destination,
                "exit_code": result.exit_code,
                "error": result.stderr[-500:] if result.stderr else "Unknown error",
            }

        return {
            "status": "success",
            "vmid": vmid,
            "node": resolved_node,
            "target_ip": ip,
            "destination": destination,
            "permissions": permissions,
            "owner": owner,
            "size_bytes": len(content.encode("utf-8")),
        }
    except Exception as e:
        logger.error("Failed to transfer file to VMID %d: %s", vmid, e)
        return format_error_response(e)


def _is_valid_permissions(perms: str) -> bool:
    """Check if a string is a valid octal permission (e.g., '0644', '755')."""
    if len(perms) not in (3, 4):
        return False
    return all(c in "01234567" for c in perms)


# ---------------------------------------------------------------------------
# Tool 4: execute_script
# ---------------------------------------------------------------------------


@mcp.tool()
async def execute_script(
    vmid: int,
    script: str,
    interpreter: str = "bash",
    timeout: int = 60,
    node: str | None = None,
    target_ip: str | None = None,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    ssh_key_path: str | None = None,
    ssh_port: int | None = None,
) -> dict:
    """Upload and execute a script on a VM or container via SSH.

    The script content is base64-encoded, transferred, executed with the
    specified interpreter, and then cleaned up.

    Args:
        vmid: The VM/CT ID to connect to.
        script: The script content to execute.
        interpreter: Script interpreter: 'bash', 'sh', 'python3', 'python', 'perl'.
        timeout: Execution timeout in seconds (max 120).
        node: Node name override. Auto-detected if omitted.
        target_ip: Direct IP/hostname of the VM. Skips auto-discovery if provided.
        ssh_user: SSH username override (defaults to global config).
        ssh_password: SSH password override (defaults to global config).
        ssh_key_path: SSH private key path override (defaults to global config).
        ssh_port: SSH port override (defaults to global config).
    """
    try:
        if not script.strip():
            raise InvalidParameterError("Script content cannot be empty.")

        validate_script_interpreter(interpreter)
        timeout = min(max(timeout, 5), 120)

        ip, resolved_node = await _get_ssh_target(vmid, node, target_ip)
        ssh_kwargs = _build_ssh_overrides(ssh_user, ssh_password, ssh_key_path, ssh_port)
        ssh = get_ssh()

        # Base64 encode and transfer via pipe to interpreter
        encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
        command = f"echo '{encoded}' | base64 -d | {interpreter}"

        result = await ssh.execute_on_host(ip, command, timeout=timeout, **ssh_kwargs)

        return {
            "status": "success" if result.success else "error",
            "vmid": vmid,
            "node": resolved_node,
            "target_ip": ip,
            "interpreter": interpreter,
            "exit_code": result.exit_code,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
        }
    except Exception as e:
        logger.error("Failed to execute script on VMID %d: %s", vmid, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Tool 5: get_system_info
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_system_info(
    vmid: int,
    node: str | None = None,
    target_ip: str | None = None,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    ssh_key_path: str | None = None,
    ssh_port: int | None = None,
) -> dict:
    """Get system information from a VM or container via SSH.

    Retrieves hostname, OS, kernel, uptime, CPU, memory, and disk usage.

    Args:
        vmid: The VM/CT ID to connect to.
        node: Node name override. Auto-detected if omitted.
        target_ip: Direct IP/hostname of the VM. Skips auto-discovery if provided.
        ssh_user: SSH username override (defaults to global config).
        ssh_password: SSH password override (defaults to global config).
        ssh_key_path: SSH private key path override (defaults to global config).
        ssh_port: SSH port override (defaults to global config).
    """
    try:
        ip, resolved_node = await _get_ssh_target(vmid, node, target_ip)
        ssh_kwargs = _build_ssh_overrides(ssh_user, ssh_password, ssh_key_path, ssh_port)
        ssh = get_ssh()

        # Gather system info in a single SSH call for efficiency
        info_script = (
            "echo '---HOSTNAME---'; hostname; "
            "echo '---OS---'; cat /etc/os-release 2>/dev/null || echo 'unknown'; "
            "echo '---KERNEL---'; uname -r; "
            "echo '---ARCH---'; uname -m; "
            "echo '---UPTIME---'; uptime -p 2>/dev/null || uptime; "
            "echo '---CPU---'; nproc 2>/dev/null || grep -c processor /proc/cpuinfo; "
            "echo '---MEMORY---'; free -b 2>/dev/null | grep Mem; "
            "echo '---DISK---'; df -B1 / 2>/dev/null | tail -1; "
            "echo '---LOAD---'; cat /proc/loadavg 2>/dev/null; "
            "echo '---END---'"
        )

        result = await ssh.execute_on_host(ip, info_script, timeout=15, **ssh_kwargs)

        if not result.success:
            return {
                "status": "error",
                "vmid": vmid,
                "node": resolved_node,
                "target_ip": ip,
                "exit_code": result.exit_code,
                "error": result.stderr[-500:] if result.stderr else "Unknown error",
            }

        info = _parse_system_info(result.stdout)
        return {
            "status": "success",
            "vmid": vmid,
            "node": resolved_node,
            "target_ip": ip,
            **info,
        }
    except Exception as e:
        logger.error("Failed to get system info from VMID %d: %s", vmid, e)
        return format_error_response(e)


def _parse_system_info(output: str) -> dict:
    """Parse the combined system info output into structured data."""
    sections: dict[str, list[str]] = {}
    current_section = ""

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("---") and stripped.endswith("---"):
            current_section = stripped.strip("-")
            sections[current_section] = []
        elif current_section and current_section != "END":
            sections.setdefault(current_section, []).append(stripped)

    info: dict = {}

    # Hostname
    info["hostname"] = sections.get("HOSTNAME", ["unknown"])[0]

    # OS
    os_lines = sections.get("OS", [])
    os_info = {}
    for line in os_lines:
        if "=" in line:
            key, _, val = line.partition("=")
            os_info[key] = val.strip('"')
    info["os"] = os_info.get("PRETTY_NAME", os_info.get("NAME", "unknown"))
    info["os_id"] = os_info.get("ID", "unknown")

    # Kernel and arch
    info["kernel"] = sections.get("KERNEL", ["unknown"])[0]
    info["architecture"] = sections.get("ARCH", ["unknown"])[0]

    # Uptime
    info["uptime"] = sections.get("UPTIME", ["unknown"])[0]

    # CPU count
    cpu_lines = sections.get("CPU", ["0"])
    try:
        info["cpu_count"] = int(cpu_lines[0])
    except ValueError:
        info["cpu_count"] = 0

    # Memory
    mem_lines = sections.get("MEMORY", [])
    if mem_lines:
        parts = mem_lines[0].split()
        # free -b output: Mem: total used free shared buff/cache available
        if len(parts) >= 4:
            try:
                info["memory"] = {
                    "total_bytes": int(parts[1]),
                    "used_bytes": int(parts[2]),
                    "free_bytes": int(parts[3]),
                    "available_bytes": int(parts[6]) if len(parts) > 6 else None,
                }
            except (ValueError, IndexError):
                info["memory"] = {"raw": mem_lines[0]}
    else:
        info["memory"] = {}

    # Disk
    disk_lines = sections.get("DISK", [])
    if disk_lines:
        parts = disk_lines[0].split()
        if len(parts) >= 5:
            try:
                info["root_disk"] = {
                    "filesystem": parts[0],
                    "total_bytes": int(parts[1]),
                    "used_bytes": int(parts[2]),
                    "available_bytes": int(parts[3]),
                    "use_percent": parts[4],
                }
            except (ValueError, IndexError):
                info["root_disk"] = {"raw": disk_lines[0]}
    else:
        info["root_disk"] = {}

    # Load average
    load_lines = sections.get("LOAD", [])
    if load_lines:
        parts = load_lines[0].split()
        if len(parts) >= 3:
            info["load_average"] = {
                "1min": parts[0],
                "5min": parts[1],
                "15min": parts[2],
            }
    else:
        info["load_average"] = {}

    return info
