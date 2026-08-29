"""SSH execution layer for running commands on Proxmox nodes and VMs."""

import asyncio
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import paramiko  # type: ignore[import-untyped]

from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.utils.errors import SSHExecutionError

logger = logging.getLogger("proxmox-mcp")

MAX_SSH_TIMEOUT = 120
# Bound the per-host SSH client cache; evict the oldest entry when full.
MAX_CACHED_CLIENTS = 8
# How long to poll for the remote command's exit status before giving up.
_EXIT_STATUS_POLL_INTERVAL = 0.05


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
    """Execute commands on Proxmox nodes and VMs over SSH."""

    def __init__(self, config: ProxmoxConfig) -> None:
        self.config = config
        self._client_cache: dict[tuple, paramiko.SSHClient] = {}
        self._client_cache_lock = threading.Lock()
        self._node_fallback_warned: set[str] = set()

    def _cache_key(
        self,
        host: str,
        *,
        port: int | None,
        username: str | None,
        key_path: str | None,
    ) -> tuple:
        effective_port = port or self.config.PROXMOX_SSH_PORT
        effective_user = username or self.config.PROXMOX_SSH_USER
        effective_key = key_path or self.config.PROXMOX_SSH_KEY_PATH
        return (host, effective_port, effective_user, effective_key)

    def _get_cached_client(
        self,
        host: str,
        *,
        port: int | None,
        username: str | None,
        password: str | None,
        key_path: str | None,
    ) -> paramiko.SSHClient:
        """Return a live cached SSH client, or create and cache a new one.

        Thread-safe: all entry points run via asyncio.to_thread. The cache is
        bounded; the oldest entry is evicted when the limit is exceeded.
        """
        key = self._cache_key(host, port=port, username=username, key_path=key_path)
        with self._client_cache_lock:
            client = self._client_cache.pop(key, None)
            if client is not None and not client.get_transport().is_active():
                client.close()
                client = None
            if client is None:
                client = self._create_client(
                    host,
                    port=port,
                    username=username,
                    password=password,
                    key_path=key_path,
                )
                # LRU-ish: re-insert; evict oldest when over the bound.
                while len(self._client_cache) >= MAX_CACHED_CLIENTS:
                    oldest = next(iter(self._client_cache))
                    old_client = self._client_cache.pop(oldest)
                    old_client.close()
                self._client_cache[key] = client
            return client

    def _discard_cached_client(
        self,
        host: str,
        *,
        port: int | None,
        username: str | None,
        key_path: str | None,
    ) -> None:
        """Remove a client from the cache (e.g. after an error) and close it."""
        key = self._cache_key(host, port=port, username=username, key_path=key_path)
        with self._client_cache_lock:
            client = self._client_cache.pop(key, None)
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def close(self) -> None:
        """Close all cached SSH clients."""
        with self._client_cache_lock:
            for client in self._client_cache.values():
                try:
                    client.close()
                except Exception:
                    pass
            self._client_cache.clear()

    def _create_client(
        self,
        host: str,
        *,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        key_path: str | None = None,
    ) -> paramiko.SSHClient:
        """Create and configure a paramiko SSH client.

        Args:
            host: Target hostname or IP.
            port: SSH port override (defaults to config).
            username: SSH username override (defaults to config).
            password: SSH password override (defaults to config).
            key_path: SSH private key path override (defaults to config).
        """
        client = paramiko.SSHClient()

        if self.config.PROXMOX_SSH_HOST_KEY_CHECKING:
            known_hosts = self.config.PROXMOX_SSH_KNOWN_HOSTS or os.path.expanduser(
                "~/.ssh/known_hosts"
            )
            if os.path.exists(known_hosts):
                client.load_host_keys(known_hosts)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            logger.warning("SSH host key checking disabled — vulnerable to MITM attacks")
            client.set_missing_host_key_policy(paramiko.WarningPolicy())

        effective_port = port or self.config.PROXMOX_SSH_PORT
        effective_user = username or self.config.PROXMOX_SSH_USER
        effective_key = key_path or self.config.PROXMOX_SSH_KEY_PATH
        effective_password = (
            password or self.config.PROXMOX_SSH_PASSWORD or self.config.PROXMOX_PASSWORD
        )

        connect_kwargs: dict = {
            "hostname": host,
            "port": effective_port,
            "username": effective_user,
            "timeout": 10,
        }

        if effective_key:
            resolved_key = Path(effective_key).expanduser()
            if not resolved_key.exists():
                raise SSHExecutionError(f"SSH key not found: {resolved_key}")
            connect_kwargs["key_filename"] = str(resolved_key)
        elif effective_password:
            connect_kwargs["password"] = effective_password
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

    def _execute_sync(
        self,
        host: str,
        command: str,
        timeout: int = 30,
        *,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        key_path: str | None = None,
    ) -> SSHResult:
        """Execute a command over SSH synchronously.

        Reuses a cached SSH client for this host/credential tuple when possible;
        the client is evicted from the cache if the command fails.
        """
        timeout = min(timeout, MAX_SSH_TIMEOUT)
        client = self._get_cached_client(
            host,
            port=port,
            username=username,
            password=password,
            key_path=key_path,
        )
        try:
            logger.debug("SSH %s: %s", host, command)
            _, stdout, stderr = client.exec_command(command)
            # Bounded wait for the remote process to exit. The exec channel's
            # timeout only covers the connect, so poll exit_status_ready here.
            deadline = time.monotonic() + timeout
            while not stdout.channel.exit_status_ready():
                if time.monotonic() >= deadline:
                    stdout.channel.close()
                    raise SSHExecutionError(
                        f"SSH command on {host} timed out after {timeout}s waiting for exit status"
                    )
                time.sleep(_EXIT_STATUS_POLL_INTERVAL)
            exit_code = stdout.channel.recv_exit_status()
            stdout_str = stdout.read().decode("utf-8", errors="replace")
            stderr_str = stderr.read().decode("utf-8", errors="replace")
            return SSHResult(
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
            )
        except SSHExecutionError:
            # Drop a broken client from the cache on command failure.
            self._discard_cached_client(host, port=port, username=username, key_path=key_path)
            raise
        except Exception as e:
            self._discard_cached_client(host, port=port, username=username, key_path=key_path)
            raise SSHExecutionError(f"SSH command failed on {host}: {e}") from e

    async def execute(self, node: str, command: str, timeout: int = 30) -> SSHResult:
        """Execute a command on a Proxmox node asynchronously.

        The node name is used directly as the SSH hostname (node DNS names
        are resolvable on the local network). If the node does not resolve,
        falls back to PROXMOX_HOST (covers single-node setups where the API
        host is also reachable via SSH).

        Args:
            node: Proxmox node name (used as hostname).
            command: Shell command to execute.
            timeout: Command timeout in seconds (max 120).
        """
        # Resolve node to hostname. For single-node setups the API host works;
        # for clusters the node name itself is typically DNS-resolvable.
        host = node
        try:
            socket.getaddrinfo(node, None)
        except socket.gaierror:
            host = self.config.PROXMOX_HOST
            if node not in self._node_fallback_warned:
                logger.warning(
                    "Node '%s' does not resolve; falling back to PROXMOX_HOST '%s' for SSH",
                    node,
                    self.config.PROXMOX_HOST,
                )
                self._node_fallback_warned.add(node)

        # Ensure sbin dirs are in PATH for system tools (parted, mkfs, etc.)
        full_command = (
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH; "
            + command
        )

        logger.debug("SSH executing on %s (%s): %s", node, host, command)
        logger.info("SSH executing on %s (%s): %s", node, host, command[:120])
        result = await asyncio.to_thread(self._execute_sync, host, full_command, timeout)

        if result.exit_code != 0:
            logger.warning(
                "SSH command exited %d on %s: stderr=%s",
                result.exit_code,
                node,
                result.stderr[:200],
            )
        return result

    async def execute_on_host(
        self,
        host: str,
        command: str,
        timeout: int = 30,
        *,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        key_path: str | None = None,
    ) -> SSHResult:
        """Execute a command on an arbitrary host (VM, container, or node) asynchronously.

        Unlike execute(), this connects directly to the given host/IP without
        resolving through Proxmox node configuration.

        Args:
            host: Target hostname or IP address.
            command: Shell command to execute.
            timeout: Command timeout in seconds (max 120).
            port: SSH port override.
            username: SSH username override.
            password: SSH password override.
            key_path: SSH private key path override.
        """
        full_command = (
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH; "
            + command
        )

        logger.debug("SSH executing on %s: %s", host, command)
        logger.info("SSH executing on %s: %s", host, command[:120])
        result = await asyncio.to_thread(
            self._execute_sync,
            host,
            full_command,
            timeout,
            port=port,
            username=username,
            password=password,
            key_path=key_path,
        )

        if result.exit_code != 0:
            logger.warning(
                "SSH command exited %d on %s: stderr=%s",
                result.exit_code,
                host,
                result.stderr[:200],
            )
        return result
