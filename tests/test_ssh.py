"""Tests for SSH execution module."""

from unittest.mock import MagicMock, patch

import paramiko
import pytest

from proxmox_mcp.ssh import SSHExecutor, SSHResult
from proxmox_mcp.utils.errors import SSHExecutionError


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.PROXMOX_HOST = "192.168.1.100"
    config.PROXMOX_SSH_PORT = 22
    config.PROXMOX_SSH_USER = "root"
    config.PROXMOX_SSH_KEY_PATH = None
    config.PROXMOX_SSH_PASSWORD = "testpass"
    config.PROXMOX_PASSWORD = None
    config.PROXMOX_SSH_HOST_KEY_CHECKING = False
    config.PROXMOX_SSH_KNOWN_HOSTS = ""
    return config


# --- SSHResult ---


class TestSSHResult:
    def test_success_property(self):
        result = SSHResult(exit_code=0, stdout="ok", stderr="")
        assert result.success is True

    def test_failure_property(self):
        result = SSHResult(exit_code=1, stdout="", stderr="error")
        assert result.success is False


# --- SSHExecutor ---


class TestSSHExecutor:
    def test_init(self, mock_config):
        executor = SSHExecutor(mock_config)
        assert executor.config is mock_config

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_execute_sync_success(self, mock_ssh_class, mock_config):
        # Setup mock SSH client
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"output data"
        mock_stdout.channel.recv_exit_status.return_value = 0

        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""

        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        executor = SSHExecutor(mock_config)
        result = executor._execute_sync("192.168.1.100", "echo hello", timeout=30)

        assert result.exit_code == 0
        assert result.stdout == "output data"
        assert result.stderr == ""
        mock_client.connect.assert_called_once()
        # Client is cached for reuse, not closed after a successful command.
        assert ("192.168.1.100", 22, "root", None) in executor._client_cache

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_execute_sync_failure(self, mock_ssh_class, mock_config):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b""
        mock_stdout.channel.recv_exit_status.return_value = 1

        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b"command not found"

        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        executor = SSHExecutor(mock_config)
        result = executor._execute_sync("192.168.1.100", "bad_command", timeout=30)

        assert result.exit_code == 1
        assert result.stderr == "command not found"

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_execute_sync_connection_error(self, mock_ssh_class, mock_config):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_client.connect.side_effect = Exception("Connection refused")

        executor = SSHExecutor(mock_config)
        with pytest.raises(SSHExecutionError, match="SSH connection"):
            executor._execute_sync("192.168.1.100", "echo hello")

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_execute_sync_with_key_path(self, mock_ssh_class, mock_config):
        mock_config.PROXMOX_SSH_KEY_PATH = "/tmp/test_key"
        mock_config.PROXMOX_SSH_PASSWORD = None

        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        # Key file doesn't exist
        executor = SSHExecutor(mock_config)
        with pytest.raises(SSHExecutionError, match="SSH key not found"):
            executor._execute_sync("192.168.1.100", "echo hello")

    @pytest.mark.asyncio
    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    async def test_execute_async(self, mock_ssh_class, mock_config):
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"async output"
        mock_stdout.channel.recv_exit_status.return_value = 0

        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""

        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)

        executor = SSHExecutor(mock_config)
        result = await executor.execute("pve1", "echo hello", timeout=30)

        assert result.exit_code == 0
        assert result.stdout == "async output"

    def test_timeout_capped_at_max(self, mock_config):
        SSHExecutor(mock_config)  # Verifies construction succeeds


class TestSSHHostKeyVerification:
    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_reject_policy_when_checking_enabled(self, mock_ssh_class, mock_config):
        mock_config.PROXMOX_SSH_HOST_KEY_CHECKING = True
        mock_config.PROXMOX_SSH_KNOWN_HOSTS = ""
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client

        # Simulate reject policy raising on unknown host
        mock_client.connect.side_effect = paramiko.SSHException("Unknown host key")

        executor = SSHExecutor(mock_config)
        with pytest.raises(SSHExecutionError, match="SSH connection"):
            executor._execute_sync("192.168.1.100", "echo hello")

        mock_client.set_missing_host_key_policy.assert_called_once()
        policy_arg = mock_client.set_missing_host_key_policy.call_args[0][0]
        assert isinstance(policy_arg, paramiko.RejectPolicy)

    @patch("proxmox_mcp.ssh.os.path.exists", return_value=True)
    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_loads_custom_known_hosts_file(self, mock_ssh_class, mock_exists, mock_config):
        mock_config.PROXMOX_SSH_HOST_KEY_CHECKING = True
        mock_config.PROXMOX_SSH_KNOWN_HOSTS = "/custom/known_hosts"
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_client.connect.side_effect = Exception("test")

        executor = SSHExecutor(mock_config)
        with pytest.raises(SSHExecutionError):
            executor._execute_sync("192.168.1.100", "echo hello")

        mock_client.load_host_keys.assert_called_once_with("/custom/known_hosts")

    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_warning_policy_when_checking_disabled(self, mock_ssh_class, mock_config):
        mock_config.PROXMOX_SSH_HOST_KEY_CHECKING = False
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_client.connect.side_effect = Exception("test")

        executor = SSHExecutor(mock_config)
        with pytest.raises(SSHExecutionError):
            executor._execute_sync("192.168.1.100", "echo hello")

        policy_arg = mock_client.set_missing_host_key_policy.call_args[0][0]
        assert isinstance(policy_arg, paramiko.WarningPolicy)

    @patch("proxmox_mcp.ssh.os.path.exists", return_value=True)
    @patch("proxmox_mcp.ssh.paramiko.SSHClient")
    def test_default_known_hosts_path(self, mock_ssh_class, mock_exists, mock_config):
        mock_config.PROXMOX_SSH_HOST_KEY_CHECKING = True
        mock_config.PROXMOX_SSH_KNOWN_HOSTS = ""  # Empty = use default
        mock_client = MagicMock()
        mock_ssh_class.return_value = mock_client
        mock_client.connect.side_effect = Exception("test")

        executor = SSHExecutor(mock_config)
        with pytest.raises(SSHExecutionError):
            executor._execute_sync("192.168.1.100", "echo hello")

        # Should load from ~/.ssh/known_hosts
        loaded_path = mock_client.load_host_keys.call_args[0][0]
        assert loaded_path.endswith(".ssh/known_hosts")
