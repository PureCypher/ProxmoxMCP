"""Proxmox API client wrapper with safety guards."""

import asyncio
import logging
import socket
import threading
import time
from collections.abc import Callable
from typing import TypeVar

import requests.exceptions  # type: ignore[import-untyped]
from proxmoxer import ProxmoxAPI
from proxmoxer.core import ResourceException

from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.utils.errors import (
    AuthenticationError,
    InsufficientPermissionsError,
    NodeNotAllowedError,
    ProtectedResourceError,
    ProxmoxConnectionError,
    ProxmoxMCPError,
    VMNotFoundError,
)
from proxmox_mcp.utils.validators import validate_node_name

logger = logging.getLogger("proxmox-mcp")

T = TypeVar("T")

# TTL (seconds) for the vmid -> node resolution cache.
_NODE_CACHE_TTL = 30


class ProxmoxClient:
    """Wrapper around proxmoxer.ProxmoxAPI with async support and safety guards."""

    def __init__(self, config: ProxmoxConfig) -> None:
        self.config = config
        self._api = self._connect(config)
        self._node_cache: dict[int, tuple[str, float]] = {}
        self._node_cache_lock = threading.Lock()

    @staticmethod
    def _connect(config: ProxmoxConfig) -> ProxmoxAPI:
        """Create a ProxmoxAPI connection from config."""
        kwargs: dict = {
            "host": config.PROXMOX_HOST,
            "port": config.PROXMOX_PORT,
            "verify_ssl": config.PROXMOX_VERIFY_SSL,
            "backend": "https",
            "timeout": 30,
        }
        if config.PROXMOX_TOKEN_NAME and config.PROXMOX_TOKEN_VALUE:
            # proxmoxer expects user and token_name as separate params.
            # Support both "user@realm!tokenid" and plain "tokenid" formats.
            token_name = config.PROXMOX_TOKEN_NAME
            if "!" in token_name:
                user, token_id = token_name.split("!", 1)
                kwargs["user"] = user
                kwargs["token_name"] = token_id
            else:
                if not config.PROXMOX_USER:
                    raise AuthenticationError(
                        "PROXMOX_TOKEN_NAME must be in 'user@realm!tokenid' format "
                        "or PROXMOX_USER must be set."
                    )
                kwargs["user"] = config.PROXMOX_USER
                kwargs["token_name"] = token_name
            kwargs["token_value"] = config.PROXMOX_TOKEN_VALUE
        elif config.PROXMOX_USER and config.PROXMOX_PASSWORD:
            kwargs["user"] = config.PROXMOX_USER
            kwargs["password"] = config.PROXMOX_PASSWORD
        else:
            raise AuthenticationError(
                "No authentication configured. "
                "Set PROXMOX_TOKEN_NAME/VALUE or PROXMOX_USER/PASSWORD."
            )
        try:
            return ProxmoxAPI(**kwargs)
        except Exception as e:
            raise ProxmoxConnectionError(f"Failed to connect to Proxmox: {e}") from e

    @property
    def api(self) -> ProxmoxAPI:
        return self._api

    async def api_call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Run a synchronous proxmoxer API call in a thread."""
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as e:
            raise self._translate_api_error(e) from e

    @staticmethod
    def _translate_api_error(e: Exception) -> Exception:
        """Classify a proxmoxer/network exception into the ProxmoxMCP hierarchy.

        Branches on the HTTP status code when available; raw response bodies are
        not echoed into error messages to avoid leaking hostnames/details.
        """
        if isinstance(e, ResourceException):
            code = getattr(e, "status_code", None)
            if code == 401:
                return AuthenticationError(
                    "Proxmox authentication failed (HTTP 401). "
                    "Check PROXMOX_TOKEN_NAME/VALUE or PROXMOX_USER/PASSWORD."
                )
            if code == 403:
                return InsufficientPermissionsError(
                    "Insufficient Proxmox permissions for this operation (HTTP 403)."
                )
            if isinstance(code, int) and code >= 400:
                return ProxmoxMCPError(
                    f"Proxmox API error (HTTP {code}). Check the Proxmox node logs for details."
                )
            return ProxmoxMCPError(f"Unexpected Proxmox API error (HTTP {code}).")
        if isinstance(
            e,
            (requests.exceptions.RequestException, ConnectionError, TimeoutError, socket.timeout),
        ):
            return ProxmoxConnectionError(
                "Could not reach the Proxmox API. "
                "Check PROXMOX_HOST/PROXMOX_PORT and that the node is reachable."
            )
        # Last-resort fallback for unexpected exception types.
        error_str = str(e).lower()
        if "401" in error_str or "authentication" in error_str:
            return AuthenticationError(
                "Proxmox authentication failed. "
                "Check PROXMOX_TOKEN_NAME/VALUE or PROXMOX_USER/PASSWORD."
            )
        if "connection" in error_str or "timeout" in error_str:
            return ProxmoxConnectionError(
                "Could not reach the Proxmox API. "
                "Check PROXMOX_HOST/PROXMOX_PORT and that the node is reachable."
            )
        return e

    async def resolve_node_for_vmid(self, vmid: int) -> str:
        """Query cluster resources to find which node owns this VMID.

        Results are cached for a short TTL to avoid a full cluster scan per call.
        """
        now = time.monotonic()
        with self._node_cache_lock:
            entry = self._node_cache.get(vmid)
            if entry is not None:
                node, stamped = entry
                if now - stamped < _NODE_CACHE_TTL:
                    return node
        try:
            node = await self._query_node_for_vmid(vmid)
        except VMNotFoundError:
            with self._node_cache_lock:
                self._node_cache.pop(vmid, None)
            raise
        with self._node_cache_lock:
            self._node_cache[vmid] = (node, now)
        return node

    async def _query_node_for_vmid(self, vmid: int) -> str:
        """Fetch the owning node for a VM/CT ID from cluster resources (uncached).

        Queries without a type filter so LXC container IDs (not just QEMU VMs)
        resolve correctly.
        """
        resources = await self.api_call(self._api.cluster.resources.get)
        for r in resources:
            if r.get("vmid") == vmid:
                return str(r["node"])
        raise VMNotFoundError(
            f"VM/CT {vmid} not found in cluster (searched {len(resources)} resources)."
        )

    async def test_connection(self) -> dict:
        """Verify connectivity by calling GET /version."""
        try:
            version = await self.api_call(self._api.version.get)
            return {"status": "connected", "version": version}
        except Exception as e:
            raise ProxmoxConnectionError(f"Connection test failed: {e}") from e

    def check_protected(self, vmid: int) -> None:
        """Raise if VMID is in the protected list."""
        if vmid in self.config.protected_vmids:
            raise ProtectedResourceError(
                f"VM/CT {vmid} is protected and cannot be modified/deleted. "
                f"Remove it from PROXMOX_PROTECTED_VMIDS to proceed."
            )

    def validate_node(self, node: str) -> None:
        """Raise if node is not in the allowed list (when allowlist is set)."""
        if self.config.allowed_nodes and node not in self.config.allowed_nodes:
            raise NodeNotAllowedError(
                f"Node '{node}' is not in the allowed nodes list: {self.config.allowed_nodes}"
            )

    def dry_run_response(self, tool_name: str, **params) -> dict:
        """Return a dry-run response dict."""
        return {
            "status": "dry_run",
            "action": tool_name,
            "params": params,
            "message": (
                "DRY RUN: This action was NOT executed. Set PROXMOX_DRY_RUN=false to perform."
            ),
        }

    async def resolve_node(self, vmid: int, node: str | None) -> str:
        """Resolve and validate a node for a VMID.

        If node is provided, validate it. Otherwise auto-detect from cluster resources.
        """
        if node:
            validate_node_name(node)
            self.validate_node(node)
            return node
        return await self.resolve_node_for_vmid(vmid)

    @property
    def is_dry_run(self) -> bool:
        return self.config.PROXMOX_DRY_RUN
