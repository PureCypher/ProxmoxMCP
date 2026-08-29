"""Hardening regression tests for SSH and disk tools.

Covers: dry-run on all 5 SSH tools, target_ip literal validation, owner
dash-rejection, ssh_port range, execute_script confirm gate, single
package-manager probe, ssh.py node fallback, and the anchored in-use grep.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxmox_mcp.ssh import SSHExecutor, SSHResult
from proxmox_mcp.utils.errors import (
    DeviceInUseError,
    InvalidParameterError,
    SSHExecutionError,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.api_call = AsyncMock(
        return_value={
            "result": [
                {
                    "name": "eth0",
                    "ip-addresses": [{"ip-address": "10.0.0.100", "ip-address-type": "ipv4"}],
                }
            ]
        }
    )
    client.validate_node = MagicMock()
    client.resolve_node = AsyncMock(return_value="pve1")
    client.is_dry_run = False
    client.dry_run_response = MagicMock(
        side_effect=lambda tool_name, **params: {
            "status": "dry_run",
            "action": tool_name,
            "params": params,
        }
    )
    return client


@pytest.fixture
def mock_ssh():
    ssh = MagicMock()
    ssh.execute = AsyncMock(return_value=SSHResult(exit_code=0, stdout="", stderr=""))
    ssh.execute_on_host = AsyncMock(return_value=SSHResult(exit_code=0, stdout="", stderr=""))
    return ssh


@contextmanager
def _patch_tools(mock_client, mock_ssh):
    with (
        patch("proxmox_mcp.tools.ssh_tools.get_client", return_value=mock_client),
        patch("proxmox_mcp.tools.ssh_tools.get_ssh", return_value=mock_ssh),
    ):
        yield


@contextmanager
def _patch_disk_tools(mock_client, mock_ssh):
    with (
        patch("proxmox_mcp.tools.disk.get_client", return_value=mock_client),
        patch("proxmox_mcp.tools.disk.get_ssh", return_value=mock_ssh),
    ):
        yield


# ---------------------------------------------------------------------------
# 1. Dry-run on all 5 SSH tools
# ---------------------------------------------------------------------------


class TestDryRun:
    async def test_install_package_dry_run(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        mock_client.is_dry_run = True
        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=["nginx"])

        assert result["status"] == "dry_run"
        assert result["action"] == "install_package"
        assert result["params"]["packages"] == ["nginx"]
        mock_ssh.execute_on_host.assert_not_awaited()
        mock_ssh.execute.assert_not_awaited()

    async def test_manage_service_dry_run(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import manage_service

        mock_client.is_dry_run = True
        with _patch_tools(mock_client, mock_ssh):
            result = await manage_service(vmid=100, service="nginx", action="start")

        assert result["status"] == "dry_run"
        assert result["action"] == "manage_service"
        mock_ssh.execute_on_host.assert_not_awaited()

    async def test_transfer_file_dry_run(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import transfer_file

        mock_client.is_dry_run = True
        with _patch_tools(mock_client, mock_ssh):
            result = await transfer_file(vmid=100, content="hello", destination="/tmp/hello")

        assert result["status"] == "dry_run"
        assert result["action"] == "transfer_file"
        mock_ssh.execute_on_host.assert_not_awaited()

    async def test_execute_script_dry_run(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        mock_client.is_dry_run = True
        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(vmid=100, script="echo hi", confirm=True)

        assert result["status"] == "dry_run"
        assert result["action"] == "execute_script"
        mock_ssh.execute_on_host.assert_not_awaited()

    async def test_get_system_info_dry_run(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import get_system_info

        mock_client.is_dry_run = True
        with _patch_tools(mock_client, mock_ssh):
            result = await get_system_info(vmid=100)

        assert result["status"] == "dry_run"
        assert result["action"] == "get_system_info"
        mock_ssh.execute_on_host.assert_not_awaited()


# ---------------------------------------------------------------------------
# 2. target_ip literal IP validation
# ---------------------------------------------------------------------------


class TestTargetIpValidation:
    async def test_valid_ipv4_literal(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import get_system_info

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0, stdout="---HOSTNAME---\nhost\n---END---\n", stderr=""
        )
        with _patch_tools(mock_client, mock_ssh):
            result = await get_system_info(vmid=100, target_ip="192.168.1.50")

        assert result["status"] == "success"
        assert result["target_ip"] == "192.168.1.50"

    @pytest.mark.parametrize(
        "bad_ip",
        [
            "host.local",
            "http://evil",
            "10.0.0.1;rm -rf /",
            "999.1.1.1",
            "myhost.example.com",
        ],
    )
    async def test_rejects_non_literal_ips(self, mock_client, mock_ssh, bad_ip):
        from proxmox_mcp.tools.ssh_tools import get_system_info

        with _patch_tools(mock_client, mock_ssh):
            result = await get_system_info(vmid=100, target_ip=bad_ip)

        assert result["status"] == "error"
        msg = result["message"]
        assert "literal IPv4 or IPv6" in msg or "forbidden characters" in msg
        mock_ssh.execute_on_host.assert_not_awaited()

    def test_validate_ip_address_direct(self):
        from proxmox_mcp.utils.sanitizers import validate_ip_address

        for good in ["169.254.169.254", "192.168.1.50", "::1", "fe80::1"]:
            validate_ip_address(good)  # should not raise
        for bad in ["host.local", "http://evil", "1.2.3"]:
            with pytest.raises(InvalidParameterError):
                validate_ip_address(bad)


# ---------------------------------------------------------------------------
# 3. owner dash rejection
# ---------------------------------------------------------------------------


class TestOwnerValidation:
    async def test_rejects_dash_prefixed_owner(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import transfer_file

        with _patch_tools(mock_client, mock_ssh):
            result = await transfer_file(
                vmid=100, content="data", destination="/tmp/x", owner="-rf /etc"
            )

        assert result["status"] == "error"
        assert "Owner" in result["message"]
        mock_ssh.execute_on_host.assert_not_awaited()

    def test_validate_owner(self):
        from proxmox_mcp.utils.sanitizers import validate_owner

        for good in ["root", "www-data:www-data", "user_1.grp", "123:456"]:
            validate_owner(good)  # should not raise
        for bad in ["-rf", "user:--group", "a b:c", "$(id)", "user::group"]:
            with pytest.raises(InvalidParameterError):
                validate_owner(bad)


# ---------------------------------------------------------------------------
# 4. ssh_port range
# ---------------------------------------------------------------------------


class TestSshPortRange:
    @pytest.mark.parametrize("bad_port", [0, -1, 65536, 70000])
    async def test_rejects_out_of_range_port(self, mock_client, mock_ssh, bad_port):
        from proxmox_mcp.tools.ssh_tools import get_system_info

        with _patch_tools(mock_client, mock_ssh):
            result = await get_system_info(vmid=100, ssh_port=bad_port)

        assert result["status"] == "error"
        assert "between 1 and 65535" in result["message"]
        mock_ssh.execute_on_host.assert_not_awaited()

    async def test_accepts_valid_port(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import get_system_info

        mock_ssh.execute_on_host.return_value = SSHResult(
            exit_code=0, stdout="---HOSTNAME---\nhost\n---END---\n", stderr=""
        )
        with _patch_tools(mock_client, mock_ssh):
            result = await get_system_info(vmid=100, ssh_port=2222)

        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# 5. execute_script confirm gate
# ---------------------------------------------------------------------------


class TestExecuteScriptConfirm:
    async def test_requires_confirm_by_default(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(vmid=100, script="rm -rf /")

        assert result["status"] == "confirmation_required"
        assert "EXECUTE ARBITRARY COMMANDS" in result["warning"]
        assert "confirm=True" in result["action"]
        mock_ssh.execute_on_host.assert_not_awaited()

    async def test_runs_with_confirm_true(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        mock_ssh.execute_on_host.return_value = SSHResult(exit_code=0, stdout="ran\n", stderr="")
        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(vmid=100, script="echo ran", confirm=True)

        assert result["status"] == "success"
        assert "ran" in result["stdout"]
        assert mock_ssh.execute_on_host.await_count == 1


# ---------------------------------------------------------------------------
# 6. Single SSH probe for package manager detection
# ---------------------------------------------------------------------------


class TestPackageManagerProbe:
    async def test_single_probe(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        mock_ssh.execute_on_host.side_effect = [
            SSHResult(exit_code=0, stdout="/usr/bin/apk\n", stderr=""),  # probe
            SSHResult(exit_code=0, stdout="OK\n", stderr=""),  # install
        ]
        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=["curl"])

        assert result["status"] == "success"
        assert result["package_manager"] == "apk"
        assert mock_ssh.execute_on_host.await_count == 2

    async def test_no_manager_found(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import install_package

        mock_ssh.execute_on_host.return_value = SSHResult(exit_code=0, stdout="", stderr="")
        with _patch_tools(mock_client, mock_ssh):
            result = await install_package(vmid=100, packages=["curl"])

        assert result["status"] == "error"
        assert "No supported package manager" in result["message"]


# ---------------------------------------------------------------------------
# 7. ssh.py node fallback
# ---------------------------------------------------------------------------


class TestNodeFallback:
    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.PROXMOX_HOST = "api-host.test"
        config.PROXMOX_SSH_PORT = 22
        config.PROXMOX_SSH_USER = "root"
        config.PROXMOX_SSH_KEY_PATH = None
        config.PROXMOX_SSH_PASSWORD = "pw"
        config.PROXMOX_PASSWORD = None
        config.PROXMOX_SSH_HOST_KEY_CHECKING = False
        config.PROXMOX_SSH_KNOWN_HOSTS = ""
        return config

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    @patch("proxmox_mcp.ssh.socket.getaddrinfo")
    async def test_node_used_when_resolvable(self, mock_getaddrinfo, mock_ssh_class, mock_config):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"ok"
        mock_stdout.channel.exit_status_ready.return_value = True
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock(read=MagicMock(return_value=b""))
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        executor = SSHExecutor(mock_config)
        await executor.execute("node1", "echo hi", timeout=10)

        # Connected to the node name, not PROXMOX_HOST
        assert mock_client.connect.call_args.kwargs["hostname"] == "node1"
        mock_getaddrinfo.assert_called_once_with("node1", None)

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    @patch("proxmox_mcp.ssh.socket.getaddrinfo")
    async def test_falls_back_to_proxmox_host(self, mock_getaddrinfo, mock_ssh_class, mock_config):
        import socket as _socket

        mock_getaddrinfo.side_effect = _socket.gaierror("unresolvable")
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"ok"
        mock_stdout.channel.exit_status_ready.return_value = True
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock(read=MagicMock(return_value=b""))
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        executor = SSHExecutor(mock_config)
        await executor.execute("node1", "echo hi", timeout=10)

        assert mock_client.connect.call_args.kwargs["hostname"] == "api-host.test"

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    @patch("proxmox_mcp.ssh.socket.getaddrinfo")
    def test_fallback_warns_only_once(self, mock_getaddrinfo, mock_ssh_class, mock_config, caplog):
        import logging
        import socket as _socket

        mock_getaddrinfo.side_effect = _socket.gaierror("unresolvable")
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"ok"
        mock_stdout.channel.exit_status_ready.return_value = True
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock(read=MagicMock(return_value=b""))
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        executor = SSHExecutor(mock_config)
        with caplog.at_level(logging.WARNING, logger="proxmox-mcp"):
            for _ in range(2):
                import asyncio

                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(executor.execute("node1", "echo hi", timeout=5))
                finally:
                    loop.close()

        warnings = [r for r in caplog.records if "falling back to PROXMOX_HOST" in r.getMessage()]
        assert len(warnings) == 1

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_client_reused_across_commands(self, mock_ssh_class, mock_config):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"ok"
        mock_stdout.channel.exit_status_ready.return_value = True
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stderr = MagicMock(read=MagicMock(return_value=b""))
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        executor = SSHExecutor(mock_config)
        executor._execute_sync("h1", "cmd1", 5)
        executor._execute_sync("h1", "cmd2", 5)

        assert mock_ssh_class.call_count == 1
        assert mock_client.exec_command.call_count == 2
        assert mock_client.close.call_count == 0

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_broken_client_evicted_on_error(self, mock_ssh_class, mock_config):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_client.exec_command.side_effect = paramiko_exception()
        mock_client.get_transport.return_value.is_active.return_value = True

        executor = SSHExecutor(mock_config)
        with pytest.raises(SSHExecutionError):
            executor._execute_sync("h1", "cmd1", 5)

        assert executor._client_cache == {}
        mock_client.close.assert_called_once()


def paramiko_exception():
    import paramiko

    return paramiko.SSHException("channel broken")


# ---------------------------------------------------------------------------
# 8. Anchored in-use grep
# ---------------------------------------------------------------------------


class TestInUseCheck:
    async def test_nvme0n10_does_not_flag_nvme0n1(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import _check_not_in_use

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="", stderr=""),  # findmnt: not mounted
            SSHResult(
                exit_code=0,
                stdout=("---LVM---\n---ZFS---\n---MD---\n---END---\n"),
                stderr="",
            ),
        ]
        with _patch_disk_tools(mock_client, mock_ssh):
            result = await _check_not_in_use(mock_ssh, "pve1", "/dev/nvme0n1")

        # The single combined probe must not prefix-match; also verify the
        # grep command itself is whole-word anchored.
        assert result is None
        probe_cmd = mock_ssh.execute.call_args_list[1][0][1]
        assert "grep -w '/dev/nvme0n1'" in probe_cmd

    async def test_in_use_device_still_detected(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import _check_not_in_use

        mock_ssh.execute.side_effect = [
            SSHResult(exit_code=0, stdout="", stderr=""),  # findmnt: not mounted
            SSHResult(
                exit_code=0,
                stdout=("---LVM---\n/dev/sdb vg0\n---ZFS---\n---MD---\n---END---\n"),
                stderr="",
            ),
        ]
        with pytest.raises(DeviceInUseError):
            with _patch_disk_tools(mock_client, mock_ssh):
                await _check_not_in_use(mock_ssh, "pve1", "/dev/sdb")

    async def test_list_disks_uses_single_ssh_probe(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.disk import list_physical_disks

        mock_client.api_call.return_value = [{"devpath": "/dev/sda", "size": 1, "used": ""}]
        mock_ssh.execute.return_value = SSHResult(
            exit_code=0,
            stdout='{"blockdevices": []}\n---LVM---\n/dev/sda\n',
            stderr="",
        )
        with _patch_disk_tools(mock_client, mock_ssh):
            result = await list_physical_disks("pve1")

        assert result["status"] == "success"
        # Only one SSH call (lsblk + pvs merged)
        assert mock_ssh.execute.await_count == 1


# ---------------------------------------------------------------------------
# 9. IP discovery: real errors surface, 404-like falls through
# ---------------------------------------------------------------------------


class TestIpDiscoveryErrors:
    async def test_both_non_404_errors_raise(self, mock_client):
        from proxmox_mcp.tools.ssh_tools import _resolve_vm_ip

        async def boom(func):
            raise Exception("401: invalid credentials")

        mock_client.api_call = AsyncMock(side_effect=boom)
        with pytest.raises(SSHExecutionError, match="IP discovery failed"):
            await _resolve_vm_ip(mock_client, 100, "pve1")

    async def test_404_like_errors_fall_through(self, mock_client):
        from proxmox_mcp.tools.ssh_tools import _resolve_vm_ip

        async def boom(func):
            raise Exception("404: Not Found")

        mock_client.api_call = AsyncMock(side_effect=boom)
        with pytest.raises(SSHExecutionError, match="Cannot discover IP"):
            await _resolve_vm_ip(mock_client, 100, "pve1")


# ---------------------------------------------------------------------------
# 10. Chunked payload
# ---------------------------------------------------------------------------


class TestChunkedPayload:
    async def test_large_script_chunked(self, mock_client, mock_ssh):
        from proxmox_mcp.tools.ssh_tools import execute_script

        mock_ssh.execute_on_host.return_value = SSHResult(exit_code=0, stdout="", stderr="")
        big_script = "echo hi\n" * 5000  # ~40KB raw -> >8KB base64 chunks
        with _patch_tools(mock_client, mock_ssh):
            result = await execute_script(vmid=100, script=big_script, confirm=True)

        assert result["status"] == "success"
        cmd = mock_ssh.execute_on_host.call_args[0][1]
        # multiple chunks appended to the temp file
        assert cmd.count("TMPF=$(mktemp)") == 1
        assert '>> "$TMPF"' in cmd
        assert "mktemp" in cmd
