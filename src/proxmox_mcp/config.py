"""Configuration management using pydantic-settings."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_VALID_TRANSPORTS = ("stdio", "streamable-http")


class ProxmoxConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Connection
    PROXMOX_HOST: str
    PROXMOX_PORT: int = 8006
    PROXMOX_VERIFY_SSL: bool = False

    # Auth Option 1: API Token (preferred)
    PROXMOX_TOKEN_NAME: str | None = None
    PROXMOX_TOKEN_VALUE: str | None = None

    # Auth Option 2: Username/Password (fallback)
    PROXMOX_USER: str | None = None
    PROXMOX_PASSWORD: str | None = None

    # Safety
    PROXMOX_DRY_RUN: bool = False
    PROXMOX_ALLOWED_NODES: str = ""
    PROXMOX_PROTECTED_VMIDS: str = ""

    # SSH (for disk management tools)
    PROXMOX_SSH_USER: str = "root"
    PROXMOX_SSH_PORT: int = 22
    PROXMOX_SSH_KEY_PATH: str | None = None
    PROXMOX_SSH_PASSWORD: str | None = None
    PROXMOX_SSH_KNOWN_HOSTS: str = ""
    PROXMOX_SSH_HOST_KEY_CHECKING: bool = True

    # Server
    MCP_TRANSPORT: str = "stdio"
    MCP_HTTP_PORT: int = 3001
    MCP_HTTP_AUTH_TOKEN: str | None = None
    LOG_LEVEL: str = "INFO"

    # Parsed list fields (built fresh by the strict validator below)
    _allowed_nodes_list: list[str] | None = None
    _protected_vmids_list: list[int] | None = None

    @model_validator(mode="after")
    def validate_strict(self) -> "ProxmoxConfig":
        """Fail loudly at startup with friendly, actionable error messages."""
        has_token = bool(self.PROXMOX_TOKEN_NAME and self.PROXMOX_TOKEN_VALUE)
        has_password = bool(self.PROXMOX_USER and self.PROXMOX_PASSWORD)
        if not has_token and not has_password:
            raise ValueError(
                "At least one Proxmox auth pair is required: set PROXMOX_TOKEN_NAME and "
                "PROXMOX_TOKEN_VALUE (preferred), or PROXMOX_USER and PROXMOX_PASSWORD."
            )
        if self.LOG_LEVEL.upper() not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"LOG_LEVEL '{self.LOG_LEVEL}' is not a valid logging level. "
                f"Allowed: {', '.join(_VALID_LOG_LEVELS)}."
            )
        if not 1 <= self.PROXMOX_PORT <= 65535:
            raise ValueError(
                f"PROXMOX_PORT must be an integer between 1 and 65535, got {self.PROXMOX_PORT}."
            )
        if not 1 <= self.MCP_HTTP_PORT <= 65535:
            raise ValueError(
                f"MCP_HTTP_PORT must be an integer between 1 and 65535, got {self.MCP_HTTP_PORT}."
            )
        if self.MCP_TRANSPORT not in _VALID_TRANSPORTS:
            raise ValueError(
                f"MCP_TRANSPORT '{self.MCP_TRANSPORT}' is invalid. "
                "Allowed: 'stdio' or 'streamable-http'."
            )

        allowed_nodes: list[str] = []
        for item in (self.PROXMOX_ALLOWED_NODES or "").split(","):
            name = item.strip()
            if name:
                allowed_nodes.append(name)
        self._allowed_nodes_list = allowed_nodes

        protected_vmids: list[int] = []
        for item in (self.PROXMOX_PROTECTED_VMIDS or "").split(","):
            raw = item.strip()
            if not raw:
                continue
            try:
                protected_vmids.append(int(raw))
            except ValueError:
                raise ValueError(
                    f"invalid VMID '{raw}' in PROXMOX_PROTECTED_VMIDS "
                    "(expected a comma-separated list of integers)."
                ) from None
        self._protected_vmids_list = protected_vmids

        return self

    @property
    def allowed_nodes(self) -> list[str]:
        """Parsed list of allowed node names."""
        return self._allowed_nodes_list or []

    @property
    def protected_vmids(self) -> list[int]:
        """Parsed list of protected VMIDs."""
        return self._protected_vmids_list or []
