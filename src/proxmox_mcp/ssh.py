"""SSH execution layer for running commands on Proxmox nodes."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import paramiko

from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.utils.errors import SSHExecutionError

logger = logging.getLogger("proxmox-mcp")

MAX_SSH_TIMEOUT = 120


@dataclass
class SSHResult:
    """Result of an SSH command execution."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class SSHExecutor:
    """Execute commands on Proxmox nodes over SSH."""

    def __init__(self, config: ProxmoxConfig) -> None:
        self.config = config

    def _create_client(self, host: str) -> paramiko.SSHClient:
        """Create and configure a paramiko SSH client."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = {
            "hostname": host,
            "port": self.config.PROXMOX_SSH_PORT,
            "username": self.config.PROXMOX_SSH_USER,
            "timeout": 10,
        }

        # Resolve SSH password: dedicated SSH password, or fall back to Proxmox API password
        ssh_password = self.config.PROXMOX_SSH_PASSWORD or self.config.PROXMOX_PASSWORD

        if self.config.PROXMOX_SSH_KEY_PATH:
            key_path = Path(self.config.PROXMOX_SSH_KEY_PATH).expanduser()
            if not key_path.exists():
                raise SSHExecutionError(f"SSH key not found: {key_path}")
            connect_kwargs["key_filename"] = str(key_path)
        elif ssh_password:
            connect_kwargs["password"] = ssh_password
            # Skip default key discovery when password is explicitly provided
            connect_kwargs["look_for_keys"] = False
            connect_kwargs["allow_agent"] = False
        # Fallback: paramiko will try default keys (~/.ssh/id_rsa, etc.)

        try:
            client.connect(**connect_kwargs)
        except Exception as e:
            client.close()
            raise SSHExecutionError(f"SSH connection to {host} failed: {e}") from e

        return client

    def _execute_sync(self, host: str, command: str, timeout: int = 30) -> SSHResult:
        """Execute a command over SSH synchronously."""
        timeout = min(timeout, MAX_SSH_TIMEOUT)
        client = self._create_client(host)
        try:
            logger.debug("SSH %s: %s", host, command)
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            stdout_str = stdout.read().decode("utf-8", errors="replace")
            stderr_str = stderr.read().decode("utf-8", errors="replace")
            return SSHResult(
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
            )
        except Exception as e:
            raise SSHExecutionError(f"SSH command failed on {host}: {e}") from e
        finally:
            client.close()

    async def execute(self, node: str, command: str, timeout: int = 30) -> SSHResult:
        """Execute a command on a Proxmox node asynchronously.

        The node name is resolved to the PROXMOX_HOST (since the API host is
        typically also reachable via SSH). For multi-node clusters, node DNS
        names are used directly.

        Args:
            node: Proxmox node name (used as hostname).
            command: Shell command to execute.
            timeout: Command timeout in seconds (max 120).
        """
        # Resolve node to hostname. For single-node setups the API host works;
        # for clusters the node name itself is typically DNS-resolvable.
        host = self.config.PROXMOX_HOST

        # Ensure sbin dirs are in PATH for system tools (parted, mkfs, etc.)
        full_command = (
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH; "
            + command
        )

        logger.info("SSH executing on %s (%s): %s", node, host, command)
        result = await asyncio.to_thread(self._execute_sync, host, full_command, timeout)

        if result.exit_code != 0:
            logger.warning(
                "SSH command exited %d on %s: stderr=%s",
                result.exit_code,
                node,
                result.stderr[:200],
            )
        return result
