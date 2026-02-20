"""Configuration management using pydantic-settings."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    PROXMOX_MAX_CONCURRENT_TASKS: int = 5

    # Server
    MCP_TRANSPORT: str = "stdio"
    MCP_HTTP_PORT: int = 3001
    LOG_LEVEL: str = "INFO"

    # Parsed list fields (set by model_validator)
    _allowed_nodes_list: list[str] = []
    _protected_vmids_list: list[int] = []

    @model_validator(mode="after")
    def parse_list_fields(self) -> "ProxmoxConfig":
        """Parse comma-separated string fields into lists."""
        raw_nodes = self.PROXMOX_ALLOWED_NODES
        if isinstance(raw_nodes, str) and raw_nodes.strip():
            self._allowed_nodes_list = [x.strip() for x in raw_nodes.split(",") if x.strip()]
        elif isinstance(raw_nodes, list):
            self._allowed_nodes_list = raw_nodes
        else:
            self._allowed_nodes_list = []

        raw_vmids = self.PROXMOX_PROTECTED_VMIDS
        if isinstance(raw_vmids, str) and raw_vmids.strip():
            self._protected_vmids_list = [
                int(x.strip()) for x in raw_vmids.split(",") if x.strip()
            ]
        elif isinstance(raw_vmids, list):
            self._protected_vmids_list = raw_vmids
        else:
            self._protected_vmids_list = []

        return self

    @property
    def allowed_nodes(self) -> list[str]:
        """Return parsed allowed nodes list."""
        return self._allowed_nodes_list

    @property
    def protected_vmids(self) -> list[int]:
        """Return parsed protected VMIDs list."""
        return self._protected_vmids_list
