"""Tests for SSH tools (install_package, manage_service, transfer_file, execute_script, get_system_info)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxmox_mcp.ssh import SSHResult


@pytest.fixture
def mock_client():
    """Create a mock ProxmoxClient."""
    client = MagicMock()
    client.api_call = AsyncMock()
    client.validate_node = MagicMock()
    client.resolve_node = AsyncMock(return_value="pve1")
    client.is_dry_run = False
    return client


@pytest.fixture
def mock_ssh():
    """Create a mock SSHExecutor."""
    ssh = MagicMock()
    ssh.execute = AsyncMock()
    ssh.execute_on_host = AsyncMock()
    return ssh


def _patch_tools(mock_client, mock_ssh, mock_interfaces=None):
    """Return a context manager that patches client, ssh, and optionally IP discovery."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        # Default: QEMU agent returns an eth0 with 10.0.0.100
        if mock_interfaces is None:
            ifaces = {
                "result": [
                    {
                        "name": "lo",
                        "ip-addresses": [
                            {"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}
                        ],
                    },
                    {
                        "name": "eth0",
                        "ip-addresses": [
                            {"ip-address": "10.0.0.100", "ip-address-type": "ipv4"}
                        ],
                    },
                ]
            }
        else:
            ifaces = mock_interfaces

        mock_client.api_call.return_value = ifaces

        with (
            patch("proxmox_mcp.tools.ssh_tools.get_client", return_value=mock_client),
            patch("proxmox_mcp.tools.ssh_tools.get_ssh", return_value=mock_ssh),
        ):
            yield

    return _ctx()


# ---------------------------------------------------------------------------
# IP Auto-Discovery
# ---------------------------------------------------------------------------


class TestResolveVmIp:
    async def test_discovers_ipv4_from_qemu_agent(self, mock_client):
        from proxmox_mcp.tools.ssh_tools import _resolve_vm_ip

        mock_client.api_call.return_value = {
            "result": [
                {
                    "name": "lo",
                    "ip-addresses": [
                        {"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}
                    ],
                },
                {
                    "name": "eth0",
                    "ip-addresses": [
                        {"ip-address": "10.0.0.50", "ip-address-type": "ipv4"},
                        {"ip-address": "fe80::1", "ip-address-type": "ipv6"},
                    ],
                },
            ]
        }

        ip = await _resolve_vm_ip(mock_client, 100, "pve1")
        assert ip == "10.0.0.50"

    async def test_skips_loopback_and_link_local(self, mock_client):
        from proxmox_mcp.tools.ssh_tools import _resolve_vm_ip

        mock_client.api_call.return_value = {
            "result": [
                {
                    "name": "lo",
                    "ip-addresses": [
                        {"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}
                    ],
                },
                {
                    "name": "eth0",
                    "ip-addresses": [
                        {"ip-address": "169.254.1.1", "ip-address-type": "ipv4"},
                        {"ip-address": "192.168.1.10", "ip-address-type": "ipv4"},
                    ],
                },
            ]
        }

        ip = await _resolve_vm_ip(mock_client, 100, "pve1")
        assert ip == "192.168.1.10"

    async def test_falls_back_to_lxc_interfaces(self, mock_client):
        from proxmox_mcp.tools.ssh_tools import _resolve_vm_ip

        # QEMU agent fails
        call_count = 0

        async def side_effect(func):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("QEMU agent not available")
            return [{"name": "eth0", "inet": "172.16.0.5/24"}]

        mock_client.api_call = side_effect

        ip = await _resolve_vm_ip(mock_client, 200, "pve1")
        assert ip == "172.16.0.5"

    async def test_raises_when_no_interfaces(self, mock_client):
        from proxmox_mcp.ssh import SSHExecutionError
        from proxmox_mcp.tools.ssh_tools import _resolve_vm_ip

        mock_client.api_call = AsyncMock(side_effect=Exception("not found"))

        with pytest.raises(SSHExecutionError, match="Cannot discover IP"):
            await _resolve_vm_ip(mock_client, 999, "pve1")


# ---------------------------------------------------------------------------
# install_package
# ---------------------------------------------------------------------------


class TestInstallPackage:
    async def test_install_success_apt(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        # First call: detect package manager
        mock_ssh.execute_on_host.side_effect = [
            SSHResult(exit_code=0, stdout="found\n", stderr=""),  # apt-get detected
            SSHResult(exit_code=0, stdout="Reading package lists...\nDone\n", stderr=""),  # install
        ]

        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=["nginx", "curl"])

        assert result["status"] == "success"
        assert result["packages"] == ["nginx", "curl"]
        assert result["package_manager"] == "apt"
        assert result["vmid"] == 100

    async def test_install_empty_packages(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=[])

        assert result["status"] == "error"
        assert "At least one package" in result["message"]

    async def test_install_invalid_package_name(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=["valid", "bad;rm -rf /"])

        assert result["status"] == "error"
        assert "forbidden characters" in result["message"]

    async def test_remove_packages(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        mock_ssh.execute_on_host.side_effect = [
            SSHResult(exit_code=0, stdout="found\n", stderr=""),  # apt-get detected
            SSHResult(exit_code=0, stdout="Removing nginx...\n", stderr=""),  # remove
        ]

        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=["nginx"], action="remove")

        assert result["status"] == "success"
        assert result["action"] == "remove"

    async def test_install_with_target_ip(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        mock_ssh.execute_on_host.side_effect = [
            SSHResult(exit_code=0, stdout="found\n", stderr=""),
            SSHResult(exit_code=0, stdout="Done\n", stderr=""),
        ]

        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(
                vmid=100, packages=["git"], target_ip="192.168.1.50"
            )

        assert result["status"] == "success"
        assert result["target_ip"] == "192.168.1.50"

    async def test_install_with_ssh_overrides(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        mock_ssh.execute_on_host.side_effect = [
            SSHResult(exit_code=0, stdout="found\n", stderr=""),
            SSHResult(exit_code=0, stdout="Done\n", stderr=""),
        ]

        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(
                vmid=100,
                packages=["htop"],
                ssh_user="admin",
                ssh_port=2222,
            )

        assert result["status"] == "success"
        # Verify SSH overrides were passed
        call_kwargs = mock_ssh.execute_on_host.call_args_list[0]
        assert call_kwargs.kwargs.get("username") == "admin"
        assert call_kwargs.kwargs.get("port") == 2222

    async def test_install_detects_dnf(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        mock_ssh.execute_on_host.side_effect = [
            SSHResult(exit_code=1, stdout="", stderr=""),  # apt-get not found
            SSHResult(exit_code=0, stdout="found\n", stderr=""),  # dnf found
            SSHResult(exit_code=0, stdout="Complete!\n", stderr=""),  # install
        ]

        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=["httpd"])

        assert result["status"] == "success"
        assert result["package_manager"] == "dnf"

    async def test_install_failure(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        mock_ssh.execute_on_host.side_effect = [
            SSHResult(exit_code=0, stdout="found\n", stderr=""),  # apt detected
            SSHResult(exit_code=100, stdout="", stderr="E: Unable to locate package foobar"),
        ]

        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=["foobar"])

        assert result["status"] == "error"
        assert result["exit_code"] == 100


# ---------------------------------------------------------------------------
# manage_service
# ---------------------------------------------------------------------------


class TestManageService:
    async def test_start_service(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import manage_service

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0, stdout="", stderr=""
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await manage_service(vmid=100, service="nginx", action="start")

        assert result["status"] == "success"
        assert result["action"] == "start"
        assert result["service"] == "nginx"

    async def test_service_status(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import manage_service

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0,
            stdout="active\nenabled\n● nginx.service - A high performance web server\n",
            stderr="",
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await manage_service(vmid=100, service="nginx", action="status")

        assert result["status"] == "success"
        assert result["is_active"] == "active"
        assert result["is_enabled"] == "enabled"

    async def test_invalid_action(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import manage_service

        with _patch_tools(mock_client, mock_ssh):
            result = await manage_service(vmid=100, service="nginx", action="destroy")

        assert result["status"] == "error"
        assert "invalid" in result["message"].lower()

    async def test_invalid_service_name(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import manage_service

        with _patch_tools(mock_client, mock_ssh):
            result = await manage_service(vmid=100, service="bad;service", action="start")

        assert result["status"] == "error"
        assert "forbidden characters" in result["message"]

    async def test_restart_failure(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import manage_service

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=1, stdout="", stderr="Failed to restart nginx.service: Unit not found."
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await manage_service(vmid=100, service="nginx", action="restart")

        assert result["status"] == "error"
        assert result["exit_code"] == 1


# ---------------------------------------------------------------------------
# transfer_file
# ---------------------------------------------------------------------------


class TestTransferFile:
    async def test_transfer_success(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import transfer_file

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0, stdout="", stderr=""
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await transfer_file(
                vmid=100,
                content="server { listen 80; }",
                destination="/etc/nginx/sites-available/default",
            )

        assert result["status"] == "success"
        assert result["destination"] == "/etc/nginx/sites-available/default"
        assert result["permissions"] == "0644"
        assert result["size_bytes"] == len("server { listen 80; }".encode())

    async def test_transfer_with_owner(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import transfer_file

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0, stdout="", stderr=""
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await transfer_file(
                vmid=100,
                content="hello",
                destination="/var/www/index.html",
                permissions="0755",
                owner="www-data:www-data",
            )

        assert result["status"] == "success"
        assert result["owner"] == "www-data:www-data"
        # Verify chown is in the command
        cmd = mock_ssh.execute_on_host.call_args[0][1]
        assert "chown www-data:www-data" in cmd

    async def test_transfer_invalid_path(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import transfer_file

        with _patch_tools(mock_client, mock_ssh):
            result = await transfer_file(
                vmid=100,
                content="data",
                destination="relative/path",
            )

        assert result["status"] == "error"
        assert "invalid" in result["message"].lower()

    async def test_transfer_path_traversal(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import transfer_file

        with _patch_tools(mock_client, mock_ssh):
            result = await transfer_file(
                vmid=100,
                content="data",
                destination="/etc/../../../tmp/evil",
            )

        assert result["status"] == "error"
        assert "traversal" in result["message"].lower()

    async def test_transfer_invalid_permissions(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import transfer_file

        with _patch_tools(mock_client, mock_ssh):
            result = await transfer_file(
                vmid=100,
                content="data",
                destination="/tmp/test",
                permissions="9999",
            )

        assert result["status"] == "error"
        assert "invalid" in result["message"].lower()


# ---------------------------------------------------------------------------
# execute_script
# ---------------------------------------------------------------------------


class TestExecuteScript:
    async def test_script_success(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0, stdout="Hello World\n", stderr=""
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(
                vmid=100,
                script='echo "Hello World"',
            )

        assert result["status"] == "success"
        assert result["exit_code"] == 0
        assert "Hello World" in result["stdout"]
        assert result["interpreter"] == "bash"

    async def test_script_python(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0, stdout="42\n", stderr=""
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(
                vmid=100,
                script="print(6 * 7)",
                interpreter="python3",
            )

        assert result["status"] == "success"
        assert result["interpreter"] == "python3"

    async def test_script_invalid_interpreter(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(
                vmid=100,
                script="echo hi",
                interpreter="ruby",
            )

        assert result["status"] == "error"
        assert "not allowed" in result["message"]

    async def test_script_empty(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(vmid=100, script="   ")

        assert result["status"] == "error"
        assert "empty" in result["message"].lower()

    async def test_script_failure(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=1, stdout="", stderr="command not found"
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(vmid=100, script="nonexistent_command")

        assert result["status"] == "error"
        assert result["exit_code"] == 1

    async def test_script_timeout_clamped(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0, stdout="ok\n", stderr=""
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(vmid=100, script="echo ok", timeout=999)

        assert result["status"] == "success"
        # Verify timeout was clamped to 120
        call_kwargs = mock_ssh.execute_on_host.call_args
        assert call_kwargs.kwargs.get("timeout", call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None) == 120


# ---------------------------------------------------------------------------
# get_system_info
# ---------------------------------------------------------------------------


class TestGetSystemInfo:
    async def test_system_info_success(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import get_system_info

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0,
            stdout=(
                "---HOSTNAME---\n"
                "web-server-01\n"
                "---OS---\n"
                'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
                'NAME="Debian GNU/Linux"\n'
                'ID=debian\n'
                "---KERNEL---\n"
                "6.1.0-18-amd64\n"
                "---ARCH---\n"
                "x86_64\n"
                "---UPTIME---\n"
                "up 5 days, 3 hours, 22 minutes\n"
                "---CPU---\n"
                "4\n"
                "---MEMORY---\n"
                "Mem:     8349024256  2147483648  4194304000  134217728  2007236608  6000000000\n"
                "---DISK---\n"
                "/dev/sda1  50000000000  15000000000  33000000000  32%  /\n"
                "---LOAD---\n"
                "0.15 0.10 0.05 1/234 5678\n"
                "---END---\n"
            ),
            stderr="",
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await get_system_info(vmid=100)

        assert result["status"] == "success"
        assert result["hostname"] == "web-server-01"
        assert "Debian" in result["os"]
        assert result["os_id"] == "debian"
        assert result["kernel"] == "6.1.0-18-amd64"
        assert result["architecture"] == "x86_64"
        assert result["cpu_count"] == 4
        assert result["memory"]["total_bytes"] == 8349024256
        assert result["root_disk"]["use_percent"] == "32%"
        assert result["load_average"]["1min"] == "0.15"

    async def test_system_info_failure(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import get_system_info

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=255, stdout="", stderr="Connection refused"
        )

        with _patch_tools(mock_client, mock_ssh):
            result = await get_system_info(vmid=100)

        assert result["status"] == "error"
        assert "Connection refused" in result["error"]


# ---------------------------------------------------------------------------
# Sanitizer tests for new validators
# ---------------------------------------------------------------------------


class TestSSHSanitizers:
    def test_valid_package_names(self):
        from proxmox_mcp.utils.sanitizers import validate_package_name

        for name in ["nginx", "python3.11", "libssl-dev", "gcc-12", "dotnet-sdk-8.0"]:
            validate_package_name(name)  # Should not raise

    def test_invalid_package_names(self):
        from proxmox_mcp.utils.errors import InvalidParameterError
        from proxmox_mcp.utils.sanitizers import validate_package_name

        for name in ["bad;pkg", "$(evil)", "pkg name", ""]:
            with pytest.raises(InvalidParameterError):
                validate_package_name(name)

    def test_valid_service_names(self):
        from proxmox_mcp.utils.sanitizers import validate_service_name

        for name in ["nginx", "docker.service", "getty@tty1", "ssh-agent"]:
            validate_service_name(name)

    def test_invalid_service_names(self):
        from proxmox_mcp.utils.errors import InvalidParameterError
        from proxmox_mcp.utils.sanitizers import validate_service_name

        for name in ["bad;svc", "$(whoami)", ""]:
            with pytest.raises(InvalidParameterError):
                validate_service_name(name)

    def test_valid_service_actions(self):
        from proxmox_mcp.utils.sanitizers import validate_service_action

        for action in ["start", "stop", "restart", "reload", "enable", "disable", "status"]:
            validate_service_action(action)

    def test_invalid_service_actions(self):
        from proxmox_mcp.utils.errors import InvalidParameterError
        from proxmox_mcp.utils.sanitizers import validate_service_action

        for action in ["destroy", "kill", "exec"]:
            with pytest.raises(InvalidParameterError):
                validate_service_action(action)

    def test_valid_remote_paths(self):
        from proxmox_mcp.utils.sanitizers import validate_remote_file_path

        for path in ["/etc/nginx/nginx.conf", "/tmp/test", "/var/www/html/index.html"]:
            validate_remote_file_path(path)

    def test_invalid_remote_paths(self):
        from proxmox_mcp.utils.errors import InvalidParameterError
        from proxmox_mcp.utils.sanitizers import validate_remote_file_path

        for path in ["relative", "/etc/../secret", "/path with spaces"]:
            with pytest.raises(InvalidParameterError):
                validate_remote_file_path(path)

    def test_valid_interpreters(self):
        from proxmox_mcp.utils.sanitizers import validate_script_interpreter

        for interp in ["bash", "sh", "python3", "python", "perl"]:
            validate_script_interpreter(interp)

    def test_invalid_interpreters(self):
        from proxmox_mcp.utils.errors import InvalidParameterError
        from proxmox_mcp.utils.sanitizers import validate_script_interpreter

        for interp in ["ruby", "node", "php"]:
            with pytest.raises(InvalidParameterError):
                validate_script_interpreter(interp)
