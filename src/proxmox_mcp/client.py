"""Proxmox API client wrapper with safety guards."""

import asyncio
import logging

from proxmoxer import ProxmoxAPI

from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.utils.errors import (
    AuthenticationError,
    NodeNotAllowedError,
    ProtectedResourceError,
    ProxmoxConnectionError,
    VMNotFoundError,
)
from proxmox_mcp.utils.validators import validate_node_name

logger = logging.getLogger("proxmox-mcp")


class ProxmoxClient:
    """Wrapper around proxmoxer.ProxmoxAPI with async support and safety guards."""

    def __init__(self, config: ProxmoxConfig) -> None:
        self.config = config
        self._api = self._connect(config)

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
                kwargs["user"] = config.PROXMOX_USER or ""
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

    async def api_call(self, func, *args, **kwargs):
        """Run a synchronous proxmoxer API call in a thread."""
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if "401" in error_str or "authentication" in error_str:
                raise AuthenticationError(f"Proxmox authentication failed: {e}") from e
            if "connection" in error_str or "timeout" in error_str:
                raise ProxmoxConnectionError(f"Proxmox connection error: {e}") from e
            raise

    async def resolve_node_for_vmid(self, vmid: int) -> str:
        """Query cluster resources to find which node owns this VMID."""
        resources = await self.api_call(self._api.cluster.resources.get, type="vm")
        for r in resources:
            if r.get("vmid") == vmid:
                return r["node"]
        raise VMNotFoundError(f"VMID {vmid} not found in cluster.")

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

    def dry_run_response(self, action: str, **params) -> dict:
        """Return a dry-run response dict."""
        return {
            "status": "dry_run",
            "action": action,
            "params": params,
            "message": (
                "DRY RUN: This action was NOT executed. "
                "Set PROXMOX_DRY_RUN=false to perform."
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
