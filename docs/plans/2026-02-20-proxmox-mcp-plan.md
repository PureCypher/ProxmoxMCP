# Proxmox VE MCP Server — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a production-grade MCP server exposing 58 Proxmox VE management tools, 10 resources, and 6 prompts.

**Architecture:** FastMCP server wrapping proxmoxer via asyncio.to_thread(). Safety guards (protected VMIDs, dry-run, node allowlist, confirmation) on all write operations. Structured JSON responses throughout.

**Tech Stack:** Python 3.11+, mcp[cli] (FastMCP), proxmoxer, pydantic-settings, pytest-asyncio

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `src/proxmox_mcp/__init__.py`
- Create: `src/proxmox_mcp/tools/__init__.py`
- Create: `src/proxmox_mcp/resources/__init__.py`
- Create: `src/proxmox_mcp/prompts/__init__.py`
- Create: `src/proxmox_mcp/utils/__init__.py`
- Create: `tests/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "proxmox-mcp-server"
version = "1.0.0"
description = "MCP server for Proxmox VE infrastructure management"
requires-python = ">=3.11"
dependencies = [
    "mcp[cli]>=1.9.0",
    "proxmoxer>=2.1.0",
    "requests>=2.31.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "urllib3>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "ruff>=0.4",
    "mypy>=1.10",
]

[project.scripts]
proxmox-mcp = "proxmox_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/proxmox_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = ["integration: marks tests requiring a live Proxmox instance"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

**Step 2: Create .env.example**

```
# Proxmox Connection
PROXMOX_HOST=192.168.1.100
PROXMOX_PORT=8006
PROXMOX_VERIFY_SSL=false

# Auth Option 1: API Token (preferred)
PROXMOX_TOKEN_NAME=root@pam!mcp-token
PROXMOX_TOKEN_VALUE=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Auth Option 2: Username/Password (fallback)
# PROXMOX_USER=root@pam
# PROXMOX_PASSWORD=secret

# Safety
PROXMOX_DRY_RUN=false
PROXMOX_ALLOWED_NODES=
PROXMOX_PROTECTED_VMIDS=
PROXMOX_MAX_CONCURRENT_TASKS=5

# Server
MCP_TRANSPORT=stdio
MCP_HTTP_PORT=3001
LOG_LEVEL=INFO
```

**Step 3: Create .gitignore**

```
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.env
.venv/
*.egg
.mypy_cache/
.pytest_cache/
.ruff_cache/
```

**Step 4: Create all `__init__.py` files** (empty files)

**Step 5: Install dependencies**

Run: `cd /Users/pure/Documents/GitHub/ProxmoxMCP && uv sync --all-extras`

**Step 6: Commit**

```bash
git add -A && git commit -m "feat: project scaffolding with pyproject.toml and directory structure"
```

---

## Task 2: Custom Exceptions (`utils/errors.py`)

**Files:**
- Create: `src/proxmox_mcp/utils/errors.py`
- Create: `tests/test_errors.py`

**Step 1: Write tests**

```python
# tests/test_errors.py
from proxmox_mcp.utils.errors import (
    ProxmoxMCPError,
    ProxmoxConnectionError,
    AuthenticationError,
    VMNotFoundError,
    ContainerNotFoundError,
    NodeNotFoundError,
    ProtectedResourceError,
    NodeNotAllowedError,
    TaskTimeoutError,
    InsufficientPermissionsError,
    InvalidParameterError,
    format_error_response,
)


def test_all_exceptions_inherit_from_base():
    for exc_class in [
        ProxmoxConnectionError, AuthenticationError, VMNotFoundError,
        ContainerNotFoundError, NodeNotFoundError, ProtectedResourceError,
        NodeNotAllowedError, TaskTimeoutError, InsufficientPermissionsError,
        InvalidParameterError,
    ]:
        assert issubclass(exc_class, ProxmoxMCPError)


def test_format_error_response():
    result = format_error_response(
        VMNotFoundError("VM 999 not found"),
        suggestion="Use list_vms to see available VMs.",
    )
    assert result["status"] == "error"
    assert result["error_type"] == "VMNotFoundError"
    assert "999" in result["message"]
    assert result["suggestion"] == "Use list_vms to see available VMs."


def test_format_error_response_no_suggestion():
    result = format_error_response(ProxmoxConnectionError("timeout"))
    assert result["status"] == "error"
    assert "suggestion" not in result
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/pure/Documents/GitHub/ProxmoxMCP && uv run pytest tests/test_errors.py -v`
Expected: FAIL (module not found)

**Step 3: Implement**

```python
# src/proxmox_mcp/utils/errors.py
"""Custom exception hierarchy for Proxmox MCP server."""


class ProxmoxMCPError(Exception):
    """Base exception for all Proxmox MCP errors."""


class ProxmoxConnectionError(ProxmoxMCPError):
    """Failed to connect to Proxmox host."""


class AuthenticationError(ProxmoxMCPError):
    """Authentication with Proxmox failed."""


class VMNotFoundError(ProxmoxMCPError):
    """QEMU VM not found in the cluster."""


class ContainerNotFoundError(ProxmoxMCPError):
    """LXC container not found in the cluster."""


class NodeNotFoundError(ProxmoxMCPError):
    """Proxmox node not found."""


class ProtectedResourceError(ProxmoxMCPError):
    """Operation blocked on a protected VMID."""


class NodeNotAllowedError(ProxmoxMCPError):
    """Node is not in the allowed nodes list."""


class TaskTimeoutError(ProxmoxMCPError):
    """A Proxmox task exceeded the timeout."""


class InsufficientPermissionsError(ProxmoxMCPError):
    """Insufficient Proxmox permissions for this operation."""


class InvalidParameterError(ProxmoxMCPError):
    """Invalid parameter value provided."""


def format_error_response(error: Exception, suggestion: str | None = None) -> dict:
    """Format any exception into a structured error response dict."""
    result = {
        "status": "error",
        "error_type": type(error).__name__,
        "message": str(error),
    }
    if suggestion:
        result["suggestion"] = suggestion
    return result
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_errors.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/proxmox_mcp/utils/errors.py tests/test_errors.py
git commit -m "feat: custom exception hierarchy and error formatter"
```

---

## Task 3: Configuration (`config.py`)

**Files:**
- Create: `src/proxmox_mcp/config.py`
- Create: `tests/test_config.py`

**Step 1: Write tests**

```python
# tests/test_config.py
import os
import pytest
from proxmox_mcp.config import ProxmoxConfig


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setenv("PROXMOX_TOKEN_NAME", "root@pam!tok")
    monkeypatch.setenv("PROXMOX_TOKEN_VALUE", "abc-123")
    config = ProxmoxConfig()
    assert config.PROXMOX_HOST == "10.0.0.1"
    assert config.PROXMOX_PORT == 8006
    assert config.PROXMOX_TOKEN_NAME == "root@pam!tok"


def test_config_defaults(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "x")
    config = ProxmoxConfig()
    assert config.PROXMOX_VERIFY_SSL is False
    assert config.PROXMOX_DRY_RUN is False
    assert config.PROXMOX_PROTECTED_VMIDS == []
    assert config.PROXMOX_ALLOWED_NODES == []
    assert config.MCP_TRANSPORT == "stdio"
    assert config.LOG_LEVEL == "INFO"


def test_config_protected_vmids_parsing(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "x")
    monkeypatch.setenv("PROXMOX_PROTECTED_VMIDS", "100,101,102")
    config = ProxmoxConfig()
    assert config.PROXMOX_PROTECTED_VMIDS == [100, 101, 102]


def test_config_allowed_nodes_parsing(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "x")
    monkeypatch.setenv("PROXMOX_ALLOWED_NODES", "pve1,pve2")
    config = ProxmoxConfig()
    assert config.PROXMOX_ALLOWED_NODES == ["pve1", "pve2"]


def test_config_empty_lists(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "x")
    monkeypatch.setenv("PROXMOX_PROTECTED_VMIDS", "")
    monkeypatch.setenv("PROXMOX_ALLOWED_NODES", "")
    config = ProxmoxConfig()
    assert config.PROXMOX_PROTECTED_VMIDS == []
    assert config.PROXMOX_ALLOWED_NODES == []


def test_config_requires_host(monkeypatch):
    monkeypatch.delenv("PROXMOX_HOST", raising=False)
    with pytest.raises(Exception):
        ProxmoxConfig()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`

**Step 3: Implement**

```python
# src/proxmox_mcp/config.py
"""Configuration management using pydantic-settings."""

from pydantic import field_validator
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
    PROXMOX_ALLOWED_NODES: list[str] = []
    PROXMOX_PROTECTED_VMIDS: list[int] = []
    PROXMOX_MAX_CONCURRENT_TASKS: int = 5

    # Server
    MCP_TRANSPORT: str = "stdio"
    MCP_HTTP_PORT: int = 3001
    LOG_LEVEL: str = "INFO"

    @field_validator("PROXMOX_PROTECTED_VMIDS", mode="before")
    @classmethod
    def parse_protected_vmids(cls, v: str | list) -> list[int]:
        if isinstance(v, list):
            return v
        if not v or not v.strip():
            return []
        return [int(x.strip()) for x in v.split(",") if x.strip()]

    @field_validator("PROXMOX_ALLOWED_NODES", mode="before")
    @classmethod
    def parse_allowed_nodes(cls, v: str | list) -> list[str]:
        if isinstance(v, list):
            return v
        if not v or not v.strip():
            return []
        return [x.strip() for x in v.split(",") if x.strip()]
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/proxmox_mcp/config.py tests/test_config.py
git commit -m "feat: pydantic-settings configuration with env var parsing"
```

---

## Task 4: Formatters & Validators

**Files:**
- Create: `src/proxmox_mcp/utils/formatters.py`
- Create: `src/proxmox_mcp/utils/validators.py`
- Create: `tests/test_formatters.py`
- Create: `tests/test_validators.py`

**Step 1: Write formatter tests**

```python
# tests/test_formatters.py
from proxmox_mcp.utils.formatters import (
    format_vm_summary,
    format_container_summary,
    format_bytes,
    format_uptime,
    format_task_result,
)


def test_format_vm_summary():
    raw = {
        "vmid": 100, "name": "test-vm", "status": "running", "node": "pve1",
        "maxcpu": 4, "maxmem": 4294967296, "mem": 2147483648,
        "maxdisk": 34359738368, "uptime": 90061, "cpu": 0.156, "tags": "web;prod",
    }
    result = format_vm_summary(raw)
    assert result["vmid"] == 100
    assert result["name"] == "test-vm"
    assert result["type"] == "qemu"
    assert result["cpu_cores"] == 4
    assert result["memory_mb"] == 4096
    assert result["memory_used_mb"] == 2048
    assert result["disk_gb"] == 32
    assert result["cpu_usage_percent"] == 15.6
    assert result["tags"] == ["web", "prod"]


def test_format_container_summary():
    raw = {
        "vmid": 200, "name": "ct-test", "status": "stopped", "node": "pve2",
        "maxcpu": 2, "maxmem": 1073741824, "mem": 0, "maxdisk": 8589934592,
        "uptime": 0, "cpu": 0,
    }
    result = format_container_summary(raw)
    assert result["type"] == "lxc"
    assert result["memory_mb"] == 1024


def test_format_bytes():
    assert format_bytes(500) == "500.0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1073741824) == "1.0 GB"
    assert format_bytes(1099511627776) == "1.0 TB"


def test_format_uptime():
    assert format_uptime(0) == "0d 0h 0m"
    assert format_uptime(90061) == "1d 1h 1m"
    assert format_uptime(3661) == "0d 1h 1m"


def test_format_task_result():
    result = format_task_result({"data": "UPID:pve1:00001234:abcdef:12345678:vzdump:100:root@pam:"})
    assert result["status"] == "submitted"
    assert "UPID" in result["task_upid"]
```

**Step 2: Write validator tests**

```python
# tests/test_validators.py
import pytest
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name
from proxmox_mcp.utils.errors import InvalidParameterError


def test_validate_vmid_valid():
    validate_vmid(100)
    validate_vmid(999999999)


def test_validate_vmid_invalid():
    with pytest.raises(InvalidParameterError):
        validate_vmid(0)
    with pytest.raises(InvalidParameterError):
        validate_vmid(-1)
    with pytest.raises(InvalidParameterError):
        validate_vmid(99)


def test_validate_node_name_valid():
    validate_node_name("pve1")
    validate_node_name("node-01")


def test_validate_node_name_invalid():
    with pytest.raises(InvalidParameterError):
        validate_node_name("")
    with pytest.raises(InvalidParameterError):
        validate_node_name("node with spaces")
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_formatters.py tests/test_validators.py -v`

**Step 4: Implement formatters**

```python
# src/proxmox_mcp/utils/formatters.py
"""Response formatting helpers for consistent tool output."""


def format_vm_summary(vm_data: dict) -> dict:
    """Standard VM summary format."""
    return {
        "vmid": vm_data.get("vmid"),
        "name": vm_data.get("name", "unnamed"),
        "status": vm_data.get("status"),
        "node": vm_data.get("node"),
        "type": "qemu",
        "cpu_cores": vm_data.get("maxcpu", 0),
        "memory_mb": vm_data.get("maxmem", 0) // (1024 * 1024),
        "memory_used_mb": vm_data.get("mem", 0) // (1024 * 1024),
        "disk_gb": vm_data.get("maxdisk", 0) // (1024 ** 3),
        "uptime_seconds": vm_data.get("uptime", 0),
        "cpu_usage_percent": round(vm_data.get("cpu", 0) * 100, 2),
        "tags": vm_data.get("tags", "").split(";") if vm_data.get("tags") else [],
    }


def format_container_summary(ct_data: dict) -> dict:
    """Standard container summary format."""
    return {
        "vmid": ct_data.get("vmid"),
        "name": ct_data.get("name", "unnamed"),
        "status": ct_data.get("status"),
        "node": ct_data.get("node"),
        "type": "lxc",
        "cpu_cores": ct_data.get("maxcpu", 0),
        "memory_mb": ct_data.get("maxmem", 0) // (1024 * 1024),
        "memory_used_mb": ct_data.get("mem", 0) // (1024 * 1024),
        "disk_gb": ct_data.get("maxdisk", 0) // (1024 ** 3),
        "uptime_seconds": ct_data.get("uptime", 0),
        "cpu_usage_percent": round(ct_data.get("cpu", 0) * 100, 2),
        "tags": ct_data.get("tags", "").split(";") if ct_data.get("tags") else [],
    }


def format_bytes(bytes_val: int) -> str:
    """Human-readable byte formatting."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def format_uptime(seconds: int) -> str:
    """Human-readable uptime."""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m"


def format_task_result(task_data: dict) -> dict:
    """Standard task result format including UPID for tracking."""
    return {
        "task_upid": task_data.get("upid") or task_data.get("data"),
        "status": "submitted",
        "message": "Task submitted successfully. Use get_task_status with the UPID to track progress.",
    }
```

**Step 5: Implement validators**

```python
# src/proxmox_mcp/utils/validators.py
"""Input validation helpers."""

import re
from proxmox_mcp.utils.errors import InvalidParameterError


def validate_vmid(vmid: int) -> None:
    """Validate VMID is in the acceptable range (100+)."""
    if vmid < 100:
        raise InvalidParameterError(
            f"VMID {vmid} is invalid. VMIDs must be >= 100."
        )


def validate_node_name(node: str) -> None:
    """Validate node name format."""
    if not node or not node.strip():
        raise InvalidParameterError("Node name cannot be empty.")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$", node):
        raise InvalidParameterError(
            f"Node name '{node}' is invalid. Must be alphanumeric with optional hyphens."
        )
```

**Step 6: Run tests**

Run: `uv run pytest tests/test_formatters.py tests/test_validators.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/proxmox_mcp/utils/formatters.py src/proxmox_mcp/utils/validators.py tests/test_formatters.py tests/test_validators.py
git commit -m "feat: response formatters and input validators"
```

---

## Task 5: Proxmox Client Wrapper

**Files:**
- Create: `src/proxmox_mcp/client.py`
- Create: `tests/test_client.py`

**Step 1: Write tests**

```python
# tests/test_client.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.utils.errors import (
    ProxmoxConnectionError,
    AuthenticationError,
    VMNotFoundError,
    ProtectedResourceError,
    NodeNotAllowedError,
)


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setenv("PROXMOX_TOKEN_NAME", "root@pam!tok")
    monkeypatch.setenv("PROXMOX_TOKEN_VALUE", "fake-token")
    return ProxmoxConfig()


@pytest.fixture
def client(mock_config):
    with patch("proxmox_mcp.client.ProxmoxAPI") as mock_api_cls:
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        c = ProxmoxClient(mock_config)
        c._api = mock_api
        return c


@pytest.mark.asyncio
async def test_resolve_node_for_vmid(client):
    client._api.cluster.resources.get.return_value = [
        {"vmid": 100, "node": "pve1", "type": "qemu"},
        {"vmid": 200, "node": "pve2", "type": "lxc"},
    ]
    node = await client.resolve_node_for_vmid(100)
    assert node == "pve1"


@pytest.mark.asyncio
async def test_resolve_node_for_vmid_not_found(client):
    client._api.cluster.resources.get.return_value = []
    with pytest.raises(VMNotFoundError):
        await client.resolve_node_for_vmid(999)


def test_check_protected_raises(mock_config, monkeypatch):
    monkeypatch.setenv("PROXMOX_PROTECTED_VMIDS", "100,101")
    config = ProxmoxConfig()
    with patch("proxmox_mcp.client.ProxmoxAPI"):
        c = ProxmoxClient(config)
        with pytest.raises(ProtectedResourceError):
            c.check_protected(100)


def test_check_protected_allows(client):
    client.check_protected(999)  # Should not raise


def test_validate_node_allowed(mock_config, monkeypatch):
    monkeypatch.setenv("PROXMOX_ALLOWED_NODES", "pve1,pve2")
    config = ProxmoxConfig()
    with patch("proxmox_mcp.client.ProxmoxAPI"):
        c = ProxmoxClient(config)
        c.validate_node("pve1")  # Should not raise
        with pytest.raises(NodeNotAllowedError):
            c.validate_node("pve3")


def test_validate_node_no_allowlist(client):
    client.validate_node("anything")  # Empty allowlist = all allowed


def test_dry_run_response(client):
    result = client.dry_run_response("delete_vm", vmid=100, node="pve1")
    assert result["status"] == "dry_run"
    assert result["action"] == "delete_vm"
    assert result["params"]["vmid"] == 100


@pytest.mark.asyncio
async def test_client_init_token_auth(mock_config):
    with patch("proxmox_mcp.client.ProxmoxAPI") as mock_cls:
        ProxmoxClient(mock_config)
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["token_name"] == "root@pam!tok"
        assert call_kwargs["token_value"] == "fake-token"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v`

**Step 3: Implement**

```python
# src/proxmox_mcp/client.py
"""Proxmox API client wrapper with safety guards."""

import asyncio
import logging
from proxmoxer import ProxmoxAPI

from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.utils.errors import (
    ProxmoxConnectionError,
    AuthenticationError,
    VMNotFoundError,
    ProtectedResourceError,
    NodeNotAllowedError,
)

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
            kwargs["token_name"] = config.PROXMOX_TOKEN_NAME
            kwargs["token_value"] = config.PROXMOX_TOKEN_VALUE
        elif config.PROXMOX_USER and config.PROXMOX_PASSWORD:
            kwargs["user"] = config.PROXMOX_USER
            kwargs["password"] = config.PROXMOX_PASSWORD
        else:
            raise AuthenticationError(
                "No authentication configured. Set PROXMOX_TOKEN_NAME/VALUE or PROXMOX_USER/PASSWORD."
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
        if vmid in self.config.PROXMOX_PROTECTED_VMIDS:
            raise ProtectedResourceError(
                f"VM/CT {vmid} is protected and cannot be modified/deleted. "
                f"Remove it from PROXMOX_PROTECTED_VMIDS to proceed."
            )

    def validate_node(self, node: str) -> None:
        """Raise if node is not in the allowed list (when allowlist is set)."""
        if self.config.PROXMOX_ALLOWED_NODES and node not in self.config.PROXMOX_ALLOWED_NODES:
            raise NodeNotAllowedError(
                f"Node '{node}' is not in the allowed nodes list: {self.config.PROXMOX_ALLOWED_NODES}"
            )

    def dry_run_response(self, action: str, **params) -> dict:
        """Return a dry-run response dict."""
        return {
            "status": "dry_run",
            "action": action,
            "params": params,
            "message": "DRY RUN: This action was NOT executed. Set PROXMOX_DRY_RUN=false to perform.",
        }

    @property
    def is_dry_run(self) -> bool:
        return self.config.PROXMOX_DRY_RUN
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/proxmox_mcp/client.py tests/test_client.py
git commit -m "feat: Proxmox client wrapper with async support and safety guards"
```

---

## Task 6: Server Skeleton & Entry Point

**Files:**
- Create: `src/proxmox_mcp/server.py`
- Create: `src/proxmox_mcp/__main__.py`

**Step 1: Implement server.py**

```python
# src/proxmox_mcp/server.py
"""FastMCP server definition and entry point for Proxmox VE Manager."""

import logging
from mcp.server.fastmcp import FastMCP

from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.client import ProxmoxClient

# Initialize config and logging
config = ProxmoxConfig()
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("proxmox-mcp")

# Create MCP server
mcp = FastMCP(
    "Proxmox VE Manager",
    json_response=True,
    instructions=(
        "You are connected to a Proxmox Virtual Environment cluster. "
        "Use the available tools to manage VMs, containers, nodes, storage, and backups. "
        "Always check the current state before making changes. "
        "For destructive operations (delete, stop, rollback), confirm with the user first. "
        "Protected VMIDs cannot be modified or deleted."
    ),
)

# Initialize Proxmox client
proxmox_client = ProxmoxClient(config)

# Import tool modules to register them with mcp
from proxmox_mcp.tools import cluster, node, storage, task  # noqa: E402, F401
from proxmox_mcp.tools import vm, container  # noqa: E402, F401
from proxmox_mcp.tools import backup, network  # noqa: E402, F401
from proxmox_mcp.resources import resources  # noqa: E402, F401
from proxmox_mcp.prompts import prompts  # noqa: E402, F401


def main():
    """Entry point for the MCP server."""
    logger.info("Starting Proxmox VE MCP Server")
    if config.MCP_TRANSPORT == "streamable-http":
        mcp.run(transport="streamable-http", port=config.MCP_HTTP_PORT)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

```python
# src/proxmox_mcp/__main__.py
"""Allow running as python -m proxmox_mcp."""
from proxmox_mcp.server import main

main()
```

> **Note:** server.py imports tool modules at module level. These modules don't exist yet — they'll be created in subsequent tasks. For now, create empty placeholder files so imports don't fail:
> - `src/proxmox_mcp/tools/cluster.py` (empty)
> - `src/proxmox_mcp/tools/node.py` (empty)
> - `src/proxmox_mcp/tools/storage.py` (empty)
> - `src/proxmox_mcp/tools/task.py` (empty)
> - `src/proxmox_mcp/tools/vm.py` (empty)
> - `src/proxmox_mcp/tools/container.py` (empty)
> - `src/proxmox_mcp/tools/backup.py` (empty)
> - `src/proxmox_mcp/tools/network.py` (empty)
> - `src/proxmox_mcp/resources/resources.py` (empty)
> - `src/proxmox_mcp/prompts/prompts.py` (empty)

**Step 2: Commit**

```bash
git add src/proxmox_mcp/server.py src/proxmox_mcp/__main__.py src/proxmox_mcp/tools/*.py src/proxmox_mcp/resources/resources.py src/proxmox_mcp/prompts/prompts.py
git commit -m "feat: server skeleton with FastMCP entry point"
```

---

## Task 7: Cluster Tools (5 tools)

**Files:**
- Create: `src/proxmox_mcp/tools/cluster.py`
- Create: `tests/test_cluster_tools.py`

**Step 1: Write tests**

```python
# tests/test_cluster_tools.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.cluster.get_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_get_cluster_status(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_status
    mock_client.api_call.return_value = [
        {"type": "cluster", "name": "pve-cluster", "quorate": 1, "nodes": 3},
        {"type": "node", "name": "pve1", "online": 1},
    ]
    result = await get_cluster_status()
    assert result["status"] == "success"
    assert "cluster_info" in result


@pytest.mark.asyncio
async def test_get_cluster_resources(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_resources
    mock_client.api_call.return_value = [
        {"type": "qemu", "vmid": 100, "name": "vm1", "status": "running", "node": "pve1"},
    ]
    result = await get_cluster_resources(resource_type="vm")
    assert result["status"] == "success"
    assert len(result["resources"]) == 1


@pytest.mark.asyncio
async def test_get_cluster_log(mock_client):
    from proxmox_mcp.tools.cluster import get_cluster_log
    mock_client.api_call.return_value = [
        {"tag": "qemu", "msg": "VM 100 started", "node": "pve1"},
    ]
    result = await get_cluster_log(max_entries=10)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_get_next_vmid(mock_client):
    from proxmox_mcp.tools.cluster import get_next_vmid
    mock_client.api_call.return_value = 103
    result = await get_next_vmid()
    assert result["status"] == "success"
    assert result["next_vmid"] == 103


@pytest.mark.asyncio
async def test_list_pools(mock_client):
    from proxmox_mcp.tools.cluster import list_pools
    mock_client.api_call.return_value = [
        {"poolid": "production", "comment": "Prod VMs"},
    ]
    result = await list_pools()
    assert result["status"] == "success"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cluster_tools.py -v`

**Step 3: Implement**

Each tool module needs access to the shared client and mcp instance. Use a `get_client()` helper that imports from `server.py`:

```python
# src/proxmox_mcp/tools/cluster.py
"""Cluster-wide operation tools."""

import logging
from proxmox_mcp.utils.errors import format_error_response

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.tool()
async def get_cluster_status() -> dict:
    """Get overall cluster health, quorum status, and node membership."""
    try:
        client = get_client()
        data = await client.api_call(client.api.cluster.status.get)
        cluster_info = {}
        nodes = []
        for item in data:
            if item.get("type") == "cluster":
                cluster_info = item
            elif item.get("type") == "node":
                nodes.append(item)
        return {
            "status": "success",
            "cluster_info": cluster_info,
            "nodes": nodes,
            "node_count": len(nodes),
        }
    except Exception as e:
        return format_error_response(e, suggestion="Check Proxmox connection settings.")


@mcp.tool()
async def get_cluster_resources(resource_type: str | None = None) -> dict:
    """List all resources (VMs, containers, storage, nodes) across the cluster.

    Args:
        resource_type: Filter by type - 'vm', 'storage', 'node', or 'sdn'. None for all.
    """
    try:
        client = get_client()
        kwargs = {}
        if resource_type:
            kwargs["type"] = resource_type
        data = await client.api_call(client.api.cluster.resources.get, **kwargs)
        return {"status": "success", "resources": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_cluster_log(max_entries: int = 50) -> dict:
    """Retrieve cluster-wide event log.

    Args:
        max_entries: Maximum number of log entries to return (default 50).
    """
    try:
        client = get_client()
        data = await client.api_call(client.api.cluster.log.get, max=max_entries)
        return {"status": "success", "log_entries": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_next_vmid() -> dict:
    """Get the next available VMID in the cluster."""
    try:
        client = get_client()
        vmid = await client.api_call(client.api.cluster.nextid.get)
        return {"status": "success", "next_vmid": int(vmid)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def list_pools() -> dict:
    """List all resource pools in the cluster."""
    try:
        client = get_client()
        data = await client.api_call(client.api.pools.get)
        return {"status": "success", "pools": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_cluster_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/proxmox_mcp/tools/cluster.py tests/test_cluster_tools.py
git commit -m "feat: cluster tools - status, resources, log, next vmid, pools"
```

---

## Task 8: Node Tools (6 tools)

**Files:**
- Modify: `src/proxmox_mcp/tools/node.py`
- Create: `tests/test_node_tools.py`

**Step 1: Write tests**

```python
# tests/test_node_tools.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.node.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_list_nodes(mock_client):
    from proxmox_mcp.tools.node import list_nodes
    mock_client.api_call.return_value = [
        {"node": "pve1", "status": "online", "maxcpu": 8, "maxmem": 17179869184,
         "mem": 8589934592, "uptime": 86400, "cpu": 0.25},
    ]
    result = await list_nodes()
    assert result["status"] == "success"
    assert len(result["nodes"]) == 1


@pytest.mark.asyncio
async def test_get_node_status(mock_client):
    from proxmox_mcp.tools.node import get_node_status
    mock_client.api_call.return_value = {
        "cpu": 0.12, "memory": {"total": 17179869184, "used": 8589934592},
        "uptime": 172800, "kversion": "6.1.0",
    }
    result = await get_node_status(node="pve1")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_get_node_status_node_not_allowed(mock_client):
    from proxmox_mcp.tools.node import get_node_status
    from proxmox_mcp.utils.errors import NodeNotAllowedError
    mock_client.validate_node.side_effect = NodeNotAllowedError("not allowed")
    result = await get_node_status(node="pve3")
    assert result["status"] == "error"
    assert "NodeNotAllowedError" in result["error_type"]
```

**Step 2: Implement**

```python
# src/proxmox_mcp/tools/node.py
"""Node status and management tools."""

import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_node_name
from proxmox_mcp.utils.formatters import format_bytes, format_uptime

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.tool()
async def list_nodes() -> dict:
    """List all nodes in the cluster with status, CPU, memory, and uptime."""
    try:
        client = get_client()
        data = await client.api_call(client.api.nodes.get)
        nodes = []
        for n in data:
            nodes.append({
                "node": n.get("node"),
                "status": n.get("status"),
                "cpu_cores": n.get("maxcpu", 0),
                "cpu_usage_percent": round(n.get("cpu", 0) * 100, 2),
                "memory_total": format_bytes(n.get("maxmem", 0)),
                "memory_used": format_bytes(n.get("mem", 0)),
                "uptime": format_uptime(n.get("uptime", 0)),
            })
        return {"status": "success", "nodes": nodes, "total": len(nodes)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_node_status(node: str) -> dict:
    """Get detailed status for a specific node including CPU, RAM, uptime, and kernel version.

    Args:
        node: The node name (e.g. 'pve1').
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).status.get)
        return {"status": "success", "node": node, "data": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_node_services(node: str) -> dict:
    """List system services on a node.

    Args:
        node: The node name.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).services.get)
        return {"status": "success", "node": node, "services": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_node_network(node: str) -> dict:
    """Get network configuration of a node.

    Args:
        node: The node name.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).network.get)
        return {"status": "success", "node": node, "networks": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_node_storage(node: str) -> dict:
    """List storage available on a node with usage info.

    Args:
        node: The node name.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).storage.get)
        return {"status": "success", "node": node, "storage": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_node_syslog(node: str, limit: int = 50, since: str | None = None) -> dict:
    """Retrieve recent syslog entries from a node.

    Args:
        node: The node name.
        limit: Maximum number of log lines to return (default 50).
        since: Only show entries since this timestamp (optional).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        kwargs = {"limit": limit}
        if since:
            kwargs["since"] = since
        data = await client.api_call(client.api.nodes(node).syslog.get, **kwargs)
        return {"status": "success", "node": node, "syslog": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_node_tools.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/proxmox_mcp/tools/node.py tests/test_node_tools.py
git commit -m "feat: node tools - list, status, services, network, storage, syslog"
```

---

## Task 9: Storage Tools (5 tools)

**Files:**
- Modify: `src/proxmox_mcp/tools/storage.py`
- Create: `tests/test_storage_tools.py`

**Step 1: Write tests**

```python
# tests/test_storage_tools.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.storage.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_list_storage(mock_client):
    from proxmox_mcp.tools.storage import list_storage
    mock_client.api_call.return_value = [
        {"storage": "local", "type": "dir", "content": "iso,vztmpl"},
        {"storage": "local-lvm", "type": "lvmthin", "content": "images,rootdir"},
    ]
    result = await list_storage()
    assert result["status"] == "success"
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_get_storage_status(mock_client):
    from proxmox_mcp.tools.storage import get_storage_status
    mock_client.api_call.return_value = {
        "total": 107374182400, "used": 53687091200, "avail": 53687091200, "active": 1,
    }
    result = await get_storage_status(node="pve1", storage="local-lvm")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_list_storage_content(mock_client):
    from proxmox_mcp.tools.storage import list_storage_content
    mock_client.api_call.return_value = [
        {"volid": "local:iso/ubuntu.iso", "format": "iso", "size": 1073741824},
    ]
    result = await list_storage_content(node="pve1", storage="local")
    assert result["status"] == "success"
```

**Step 2: Implement**

```python
# src/proxmox_mcp/tools/storage.py
"""Storage management tools."""

import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_node_name

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.tool()
async def list_storage() -> dict:
    """List all storage pools cluster-wide with type and content info."""
    try:
        client = get_client()
        data = await client.api_call(client.api.storage.get)
        return {"status": "success", "storage": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_storage_status(node: str, storage: str) -> dict:
    """Get usage and status of a specific storage pool on a node.

    Args:
        node: The node name.
        storage: The storage pool name (e.g. 'local-lvm').
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).storage(storage).status.get)
        return {"status": "success", "node": node, "storage": storage, "data": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def list_storage_content(
    node: str, storage: str, content_type: str | None = None
) -> dict:
    """List contents of a storage pool (ISOs, templates, backups, disk images).

    Args:
        node: The node name.
        storage: The storage pool name.
        content_type: Filter by type - 'images', 'iso', 'vztmpl', 'backup', 'rootdir'. None for all.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        kwargs = {}
        if content_type:
            kwargs["content"] = content_type
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, **kwargs
        )
        return {"status": "success", "node": node, "storage": storage, "content": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_available_isos(node: str, storage: str = "local") -> dict:
    """List available ISO images for VM creation.

    Args:
        node: The node name.
        storage: The storage pool to search (default 'local').
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, content="iso"
        )
        return {"status": "success", "node": node, "storage": storage, "isos": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_available_templates(node: str, storage: str = "local") -> dict:
    """List available container templates for LXC creation.

    Args:
        node: The node name.
        storage: The storage pool to search (default 'local').
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, content="vztmpl"
        )
        return {"status": "success", "node": node, "storage": storage, "templates": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_storage_tools.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/proxmox_mcp/tools/storage.py tests/test_storage_tools.py
git commit -m "feat: storage tools - list, status, content, ISOs, templates"
```

---

## Task 10: Task Tracking Tools (4 tools)

**Files:**
- Modify: `src/proxmox_mcp/tools/task.py`
- Create: `tests/test_task_tools.py`

**Step 1: Write tests**

```python
# tests/test_task_tools.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.task.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_list_tasks(mock_client):
    from proxmox_mcp.tools.task import list_tasks
    mock_client.api_call.return_value = [
        {"upid": "UPID:pve1:001", "type": "qmstart", "status": "OK", "node": "pve1"},
    ]
    result = await list_tasks(node="pve1")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_get_task_status(mock_client):
    from proxmox_mcp.tools.task import get_task_status
    mock_client.api_call.return_value = {"status": "running", "type": "vzdump"}
    result = await get_task_status(node="pve1", upid="UPID:pve1:001")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_get_task_log(mock_client):
    from proxmox_mcp.tools.task import get_task_log
    mock_client.api_call.return_value = [
        {"n": 1, "t": "INFO: starting backup"},
    ]
    result = await get_task_log(node="pve1", upid="UPID:pve1:001")
    assert result["status"] == "success"
```

**Step 2: Implement**

```python
# src/proxmox_mcp/tools/task.py
"""Task tracking and status tools."""

import asyncio
import logging
from proxmox_mcp.utils.errors import format_error_response, TaskTimeoutError
from proxmox_mcp.utils.validators import validate_node_name

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.tool()
async def list_tasks(
    node: str | None = None, limit: int = 20, status_filter: str | None = None
) -> dict:
    """List recent tasks on a node or cluster-wide.

    Args:
        node: The node to query. If None, queries all nodes.
        limit: Maximum number of tasks to return (default 20).
        status_filter: Filter by status - 'running', 'completed', or 'error'.
    """
    try:
        client = get_client()
        if node:
            validate_node_name(node)
            client.validate_node(node)
            nodes = [node]
        else:
            node_data = await client.api_call(client.api.nodes.get)
            nodes = [n["node"] for n in node_data]
        all_tasks = []
        for n in nodes:
            kwargs = {"limit": limit}
            if status_filter == "running":
                kwargs["source"] = "active"
            data = await client.api_call(client.api.nodes(n).tasks.get, **kwargs)
            all_tasks.extend(data)
        if status_filter == "error":
            all_tasks = [t for t in all_tasks if t.get("status", "") not in ("", "OK")]
        elif status_filter == "completed":
            all_tasks = [t for t in all_tasks if t.get("status") == "OK"]
        return {"status": "success", "tasks": all_tasks[:limit], "total": len(all_tasks[:limit])}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_task_status(node: str, upid: str) -> dict:
    """Get status of a specific task by UPID.

    Args:
        node: The node where the task is running.
        upid: The task UPID string.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).tasks(upid).status.get)
        return {"status": "success", "node": node, "upid": upid, "task_status": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_task_log(node: str, upid: str, limit: int = 100) -> dict:
    """Get log output of a specific task.

    Args:
        node: The node where the task ran.
        upid: The task UPID string.
        limit: Maximum number of log lines (default 100).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).tasks(upid).log.get, limit=limit)
        return {"status": "success", "node": node, "upid": upid, "log": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def wait_for_task(
    node: str, upid: str, timeout: int = 300, poll_interval: int = 5
) -> dict:
    """Poll a task until completion or timeout.

    Args:
        node: The node where the task is running.
        upid: The task UPID string.
        timeout: Maximum seconds to wait (default 300).
        poll_interval: Seconds between status checks (default 5).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        elapsed = 0
        while elapsed < timeout:
            data = await client.api_call(client.api.nodes(node).tasks(upid).status.get)
            status = data.get("status")
            if status and status != "running":
                return {
                    "status": "success",
                    "task_status": status,
                    "exitstatus": data.get("exitstatus", ""),
                    "upid": upid,
                    "elapsed_seconds": elapsed,
                }
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TaskTimeoutError(f"Task {upid} did not complete within {timeout}s.")
    except TaskTimeoutError:
        return format_error_response(
            TaskTimeoutError(f"Task {upid} timed out after {timeout}s."),
            suggestion="Increase timeout or check task status manually with get_task_status.",
        )
    except Exception as e:
        return format_error_response(e)
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_task_tools.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/proxmox_mcp/tools/task.py tests/test_task_tools.py
git commit -m "feat: task tools - list, status, log, wait_for_task"
```

---

## Task 11: VM Tools — Read Operations (5 tools)

**Files:**
- Modify: `src/proxmox_mcp/tools/vm.py`
- Create: `tests/test_vm_tools.py`

**Step 1: Write tests**

```python
# tests/test_vm_tools.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.vm.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.config.PROXMOX_DRY_RUN = False
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_list_vms(mock_client):
    from proxmox_mcp.tools.vm import list_vms
    mock_client.api_call.return_value = [
        {"vmid": 100, "name": "vm1", "status": "running", "node": "pve1",
         "maxcpu": 2, "maxmem": 2147483648, "mem": 1073741824,
         "maxdisk": 34359738368, "uptime": 3600, "cpu": 0.05},
    ]
    result = await list_vms()
    assert result["status"] == "success"
    assert len(result["vms"]) == 1
    assert result["vms"][0]["type"] == "qemu"


@pytest.mark.asyncio
async def test_list_vms_filter_running(mock_client):
    from proxmox_mcp.tools.vm import list_vms
    mock_client.api_call.return_value = [
        {"vmid": 100, "status": "running", "name": "a", "maxcpu": 1, "maxmem": 0, "mem": 0, "maxdisk": 0, "uptime": 0, "cpu": 0},
        {"vmid": 101, "status": "stopped", "name": "b", "maxcpu": 1, "maxmem": 0, "mem": 0, "maxdisk": 0, "uptime": 0, "cpu": 0},
    ]
    result = await list_vms(status_filter="running")
    assert len(result["vms"]) == 1


@pytest.mark.asyncio
async def test_get_vm_status(mock_client):
    from proxmox_mcp.tools.vm import get_vm_status
    mock_client.api_call.return_value = {
        "status": "running", "vmid": 100, "name": "test", "qmpstatus": "running",
        "cpu": 0.1, "maxmem": 2147483648, "mem": 1073741824,
    }
    result = await get_vm_status(vmid=100)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_get_vm_status_auto_detect_node(mock_client):
    from proxmox_mcp.tools.vm import get_vm_status
    mock_client.api_call.return_value = {"status": "running", "vmid": 100}
    result = await get_vm_status(vmid=100)
    mock_client.resolve_node_for_vmid.assert_called_once_with(100)


@pytest.mark.asyncio
async def test_get_vm_config(mock_client):
    from proxmox_mcp.tools.vm import get_vm_config
    mock_client.api_call.return_value = {
        "name": "test", "memory": 2048, "cores": 2, "sockets": 1,
    }
    result = await get_vm_config(vmid=100)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_get_vm_rrd_data(mock_client):
    from proxmox_mcp.tools.vm import get_vm_rrd_data
    mock_client.api_call.return_value = [{"time": 1000, "cpu": 0.1}]
    result = await get_vm_rrd_data(vmid=100, timeframe="hour")
    assert result["status"] == "success"
```

**Step 2: Implement the read-only VM tools**

```python
# src/proxmox_mcp/tools/vm.py
"""QEMU/KVM VM management tools."""

import json
import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name
from proxmox_mcp.utils.formatters import format_vm_summary, format_task_result

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


async def _resolve_node(client, vmid: int, node: str | None) -> str:
    """Resolve node for a VMID, auto-detecting if not provided."""
    if node:
        validate_node_name(node)
        client.validate_node(node)
        return node
    return await client.resolve_node_for_vmid(vmid)


@mcp.tool()
async def list_vms(node: str | None = None, status_filter: str | None = None) -> dict:
    """List all QEMU VMs across the cluster or on a specific node.

    Args:
        node: Filter to a specific node. None for all nodes.
        status_filter: Filter by status - 'running', 'stopped', or None for all.
    """
    try:
        client = get_client()
        if node:
            validate_node_name(node)
            client.validate_node(node)
        resources = await client.api_call(client.api.cluster.resources.get, type="vm")
        vms = [r for r in resources if r.get("type") == "qemu"]
        if node:
            vms = [v for v in vms if v.get("node") == node]
        if status_filter:
            vms = [v for v in vms if v.get("status") == status_filter]
        formatted = [format_vm_summary(v) for v in vms]
        return {"status": "success", "vms": formatted, "total": len(formatted)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_vm_status(vmid: int, node: str | None = None) -> dict:
    """Get detailed status of a specific QEMU VM.

    Args:
        vmid: The VM ID (e.g. 100).
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        data = await client.api_call(client.api.nodes(node).qemu(vmid).status.current.get)
        return {"status": "success", "vmid": vmid, "node": node, "data": data}
    except Exception as e:
        return format_error_response(e, suggestion="Use list_vms to see available VMs.")


@mcp.tool()
async def get_vm_config(vmid: int, node: str | None = None) -> dict:
    """Get full configuration of a QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        data = await client.api_call(client.api.nodes(node).qemu(vmid).config.get)
        return {"status": "success", "vmid": vmid, "node": node, "config": data}
    except Exception as e:
        return format_error_response(e, suggestion="Use list_vms to see available VMs.")


@mcp.tool()
async def get_vm_rrd_data(
    vmid: int, node: str | None = None, timeframe: str = "hour"
) -> dict:
    """Get VM performance metrics (CPU, memory, disk, network) over time.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
        timeframe: Time range - 'hour', 'day', 'week', 'month', or 'year'.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        data = await client.api_call(
            client.api.nodes(node).qemu(vmid).rrddata.get, timeframe=timeframe
        )
        return {"status": "success", "vmid": vmid, "node": node, "timeframe": timeframe, "data": data}
    except Exception as e:
        return format_error_response(e)
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_vm_tools.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/proxmox_mcp/tools/vm.py tests/test_vm_tools.py
git commit -m "feat: VM read tools - list, status, config, rrd data"
```

---

## Task 12: VM Tools — Write & Destructive Operations (11 tools)

**Files:**
- Modify: `src/proxmox_mcp/tools/vm.py` (append to existing)
- Modify: `tests/test_vm_tools.py` (append to existing)

**Step 1: Add tests for write operations to `tests/test_vm_tools.py`**

Append these tests:

```python
# Append to tests/test_vm_tools.py

@pytest.mark.asyncio
async def test_start_vm(mock_client):
    from proxmox_mcp.tools.vm import start_vm
    mock_client.api_call.return_value = "UPID:pve1:00001:start"
    result = await start_vm(vmid=100)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_stop_vm(mock_client):
    from proxmox_mcp.tools.vm import stop_vm
    mock_client.api_call.return_value = "UPID:pve1:00002:stop"
    result = await stop_vm(vmid=100)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_stop_vm_protected(mock_client):
    from proxmox_mcp.tools.vm import stop_vm
    from proxmox_mcp.utils.errors import ProtectedResourceError
    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await stop_vm(vmid=100)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_stop_vm_dry_run(mock_client):
    from proxmox_mcp.tools.vm import stop_vm
    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run", "action": "stop_vm", "params": {}, "message": "DRY RUN"}
    result = await stop_vm(vmid=100)
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_shutdown_vm(mock_client):
    from proxmox_mcp.tools.vm import shutdown_vm
    mock_client.api_call.return_value = "UPID:pve1:00003:shutdown"
    result = await shutdown_vm(vmid=100)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_delete_vm_requires_confirm(mock_client):
    from proxmox_mcp.tools.vm import delete_vm
    mock_client.api_call.return_value = {"status": "running", "vmid": 100, "name": "test"}
    result = await delete_vm(vmid=100)
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_delete_vm_confirmed(mock_client):
    from proxmox_mcp.tools.vm import delete_vm
    mock_client.api_call.return_value = "UPID:pve1:00010:destroy"
    result = await delete_vm(vmid=100, confirm=True)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_clone_vm(mock_client):
    from proxmox_mcp.tools.vm import clone_vm
    mock_client.api_call.return_value = "UPID:pve1:00004:clone"
    result = await clone_vm(vmid=100, newid=200, name="clone-vm")
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_create_vm(mock_client):
    from proxmox_mcp.tools.vm import create_vm
    mock_client.api_call.return_value = "UPID:pve1:00005:create"
    result = await create_vm(node="pve1", name="new-vm")
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_modify_vm_config(mock_client):
    from proxmox_mcp.tools.vm import modify_vm_config
    mock_client.api_call.return_value = None
    result = await modify_vm_config(vmid=100, memory=4096, cores=4)
    assert result["status"] == "success"
```

**Step 2: Append write tools to `src/proxmox_mcp/tools/vm.py`**

```python
# Append to src/proxmox_mcp/tools/vm.py


@mcp.tool()
async def start_vm(vmid: int, node: str | None = None, timeout: int = 60) -> dict:
    """Start a stopped QEMU VM.

    Args:
        vmid: The VM ID to start.
        node: The node name. Auto-detected if omitted.
        timeout: Timeout in seconds (default 60).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("start_vm", vmid=vmid, node=node)
        logger.info("Starting VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.start.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def stop_vm(vmid: int, node: str | None = None) -> dict:
    """Hard stop a QEMU VM (like pulling power). Use shutdown_vm for graceful stop.

    Args:
        vmid: The VM ID to stop.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("stop_vm", vmid=vmid, node=node)
        logger.warning("Hard stopping VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.stop.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def shutdown_vm(vmid: int, node: str | None = None, timeout: int = 120) -> dict:
    """Graceful ACPI shutdown of a QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
        timeout: Timeout in seconds for the shutdown (default 120).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("shutdown_vm", vmid=vmid, node=node)
        logger.info("Graceful shutdown of VM %d on %s", vmid, node)
        upid = await client.api_call(
            client.api.nodes(node).qemu(vmid).status.shutdown.post, timeout=timeout
        )
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def reboot_vm(vmid: int, node: str | None = None) -> dict:
    """Reboot a QEMU VM via ACPI.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("reboot_vm", vmid=vmid, node=node)
        logger.info("Rebooting VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.reboot.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def suspend_vm(vmid: int, node: str | None = None) -> dict:
    """Suspend/pause a running QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("suspend_vm", vmid=vmid, node=node)
        logger.info("Suspending VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.suspend.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def resume_vm(vmid: int, node: str | None = None) -> dict:
    """Resume a suspended QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("resume_vm", vmid=vmid, node=node)
        logger.info("Resuming VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.resume.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def reset_vm(vmid: int, node: str | None = None) -> dict:
    """Hard reset a QEMU VM.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("reset_vm", vmid=vmid, node=node)
        logger.warning("Hard resetting VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).status.reset.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def clone_vm(
    vmid: int,
    newid: int,
    name: str,
    node: str | None = None,
    full: bool = True,
    target_node: str | None = None,
    target_storage: str | None = None,
) -> dict:
    """Clone a QEMU VM (full or linked clone).

    Args:
        vmid: Source VM ID to clone.
        newid: New VMID for the clone.
        name: Name for the cloned VM.
        node: Source node. Auto-detected if omitted.
        full: True for full clone, False for linked clone (default True).
        target_node: Destination node for the clone (optional).
        target_storage: Storage for the clone's disks (optional).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_vmid(newid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("clone_vm", vmid=vmid, newid=newid, name=name, node=node)
        kwargs = {"newid": newid, "name": name, "full": 1 if full else 0}
        if target_node:
            kwargs["target"] = target_node
        if target_storage:
            kwargs["storage"] = target_storage
        logger.info("Cloning VM %d to %d (%s) on %s", vmid, newid, name, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).clone.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def migrate_vm(
    vmid: int, target_node: str, node: str | None = None, online: bool = True
) -> dict:
    """Live-migrate a QEMU VM to another node.

    Args:
        vmid: The VM ID to migrate.
        target_node: Destination node.
        node: Source node. Auto-detected if omitted.
        online: True for live migration (default), False for offline.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("migrate_vm", vmid=vmid, target=target_node, node=node)
        logger.info("Migrating VM %d from %s to %s (online=%s)", vmid, node, target_node, online)
        upid = await client.api_call(
            client.api.nodes(node).qemu(vmid).migrate.post,
            target=target_node, online=1 if online else 0,
        )
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def create_vm(
    node: str,
    name: str,
    vmid: int | None = None,
    memory: int = 2048,
    cores: int = 2,
    sockets: int = 1,
    iso: str | None = None,
    disk_size: str = "32G",
    storage: str = "local-lvm",
    net_bridge: str = "vmbr0",
    os_type: str = "l26",
    start_after_create: bool = False,
) -> dict:
    """Create a new QEMU VM.

    Args:
        node: Node to create the VM on.
        name: VM name.
        vmid: Specific VMID, or None to auto-assign.
        memory: RAM in MB (default 2048).
        cores: CPU cores (default 2).
        sockets: CPU sockets (default 1).
        iso: ISO image path for CD-ROM (e.g. 'local:iso/ubuntu.iso').
        disk_size: Root disk size (default '32G').
        storage: Storage pool for disks (default 'local-lvm').
        net_bridge: Network bridge (default 'vmbr0').
        os_type: OS type identifier (default 'l26' for Linux 2.6+).
        start_after_create: Start the VM after creation (default False).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        if vmid:
            validate_vmid(vmid)
        if client.is_dry_run:
            return client.dry_run_response("create_vm", node=node, name=name, vmid=vmid)
        kwargs = {
            "name": name,
            "memory": memory,
            "cores": cores,
            "sockets": sockets,
            "ostype": os_type,
            "scsi0": f"{storage}:{disk_size}",
            "scsihw": "virtio-scsi-single",
            "net0": f"virtio,bridge={net_bridge}",
            "start": 1 if start_after_create else 0,
        }
        if vmid:
            kwargs["vmid"] = vmid
        if iso:
            kwargs["cdrom"] = iso
        logger.info("Creating VM '%s' on %s", name, node)
        upid = await client.api_call(client.api.nodes(node).qemu.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_vm(
    vmid: int,
    node: str | None = None,
    purge: bool = True,
    destroy_unreferenced_disks: bool = True,
    confirm: bool = False,
) -> dict:
    """Permanently delete/destroy a QEMU VM. Set confirm=True to execute.

    Args:
        vmid: The VM ID to delete.
        node: The node name. Auto-detected if omitted.
        purge: Remove from all configurations (default True).
        destroy_unreferenced_disks: Delete associated disks (default True).
        confirm: Must be True to actually delete. False returns a confirmation prompt.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if not confirm:
            vm_data = await client.api_call(client.api.nodes(node).qemu(vmid).status.current.get)
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will PERMANENTLY DELETE VM {vmid} ({vm_data.get('name', 'unnamed')}). "
                    f"All disks and data will be destroyed. This cannot be undone."
                ),
                "action": "Call delete_vm again with confirm=True to proceed.",
                "vm_info": {"vmid": vmid, "name": vm_data.get("name"), "node": node, "status": vm_data.get("status")},
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_vm", vmid=vmid, node=node)
        kwargs = {}
        if purge:
            kwargs["purge"] = 1
        if destroy_unreferenced_disks:
            kwargs["destroy-unreferenced-disks"] = 1
        logger.warning("DELETING VM %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).qemu(vmid).delete, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def modify_vm_config(
    vmid: int,
    node: str | None = None,
    memory: int | None = None,
    cores: int | None = None,
    sockets: int | None = None,
    name: str | None = None,
    description: str | None = None,
    balloon: int | None = None,
    cpu_type: str | None = None,
    onboot: bool | None = None,
    tags: str | None = None,
    extra_config: str | None = None,
) -> dict:
    """Modify QEMU VM configuration.

    Args:
        vmid: The VM ID.
        node: The node name. Auto-detected if omitted.
        memory: RAM in MB.
        cores: CPU cores.
        sockets: CPU sockets.
        name: VM name.
        description: VM description.
        balloon: Balloon memory in MB (0 to disable).
        cpu_type: CPU type (e.g. 'host', 'kvm64').
        onboot: Start on boot.
        tags: Semicolon-separated tags.
        extra_config: JSON string of additional config key/value pairs.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("modify_vm_config", vmid=vmid, node=node)
        kwargs = {}
        if memory is not None:
            kwargs["memory"] = memory
        if cores is not None:
            kwargs["cores"] = cores
        if sockets is not None:
            kwargs["sockets"] = sockets
        if name is not None:
            kwargs["name"] = name
        if description is not None:
            kwargs["description"] = description
        if balloon is not None:
            kwargs["balloon"] = balloon
        if cpu_type is not None:
            kwargs["cpu"] = cpu_type
        if onboot is not None:
            kwargs["onboot"] = 1 if onboot else 0
        if tags is not None:
            kwargs["tags"] = tags
        if extra_config:
            extra = json.loads(extra_config)
            kwargs.update(extra)
        if not kwargs:
            return {"status": "error", "error_type": "InvalidParameterError",
                    "message": "No configuration changes specified."}
        logger.info("Modifying VM %d config on %s: %s", vmid, node, list(kwargs.keys()))
        await client.api_call(client.api.nodes(node).qemu(vmid).config.put, **kwargs)
        return {"status": "success", "vmid": vmid, "node": node, "changes": list(kwargs.keys())}
    except json.JSONDecodeError:
        return format_error_response(
            Exception("extra_config must be valid JSON"),
            suggestion='Example: \'{"boot": "order=scsi0;net0"}\'',
        )
    except Exception as e:
        return format_error_response(e)
```

**Step 3: Run all VM tests**

Run: `uv run pytest tests/test_vm_tools.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/proxmox_mcp/tools/vm.py tests/test_vm_tools.py
git commit -m "feat: VM write tools - start, stop, shutdown, reboot, clone, migrate, create, delete, modify"
```

---

## Task 13: Container Tools — All Operations (13 tools)

**Files:**
- Modify: `src/proxmox_mcp/tools/container.py`
- Create: `tests/test_container_tools.py`

Container tools follow the **exact same pattern** as VM tools. The key differences:
- API path: `nodes(node).lxc(vmid)` instead of `nodes(node).qemu(vmid)`
- Formatter: `format_container_summary()` instead of `format_vm_summary()`
- Resource type filter: `"lxc"` instead of `"qemu"`
- `create_container` takes `ostemplate`, `hostname`, `password`, `ssh_public_keys`, `swap`, `rootfs_size`, `ip_config`, `unprivileged`
- No `reset_vm` equivalent, no `suspend/resume`, no `rrd_data`
- Has `reboot_container` instead

**Step 1: Write tests**

```python
# tests/test_container_tools.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.container.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.config.PROXMOX_DRY_RUN = False
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_list_containers(mock_client):
    from proxmox_mcp.tools.container import list_containers
    mock_client.api_call.return_value = [
        {"vmid": 200, "name": "ct1", "status": "running", "node": "pve1",
         "type": "lxc", "maxcpu": 1, "maxmem": 536870912, "mem": 268435456,
         "maxdisk": 8589934592, "uptime": 3600, "cpu": 0.02},
    ]
    result = await list_containers()
    assert result["status"] == "success"
    assert result["containers"][0]["type"] == "lxc"


@pytest.mark.asyncio
async def test_get_container_status(mock_client):
    from proxmox_mcp.tools.container import get_container_status
    mock_client.api_call.return_value = {"status": "running", "vmid": 200}
    result = await get_container_status(vmid=200)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_start_container(mock_client):
    from proxmox_mcp.tools.container import start_container
    mock_client.api_call.return_value = "UPID:pve1:00001:start"
    result = await start_container(vmid=200)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_stop_container_protected(mock_client):
    from proxmox_mcp.tools.container import stop_container
    from proxmox_mcp.utils.errors import ProtectedResourceError
    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await stop_container(vmid=200)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_delete_container_requires_confirm(mock_client):
    from proxmox_mcp.tools.container import delete_container
    mock_client.api_call.return_value = {"status": "stopped", "vmid": 200, "name": "test-ct"}
    result = await delete_container(vmid=200)
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_create_container(mock_client):
    from proxmox_mcp.tools.container import create_container
    mock_client.api_call.return_value = "UPID:pve1:00006:create"
    result = await create_container(
        node="pve1", ostemplate="local:vztmpl/ubuntu-22.04.tar.zst", hostname="test-ct"
    )
    assert result["status"] == "submitted"
```

**Step 2: Implement**

```python
# src/proxmox_mcp/tools/container.py
"""LXC container management tools."""

import json
import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name
from proxmox_mcp.utils.formatters import format_container_summary, format_task_result

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


async def _resolve_node(client, vmid: int, node: str | None) -> str:
    if node:
        validate_node_name(node)
        client.validate_node(node)
        return node
    return await client.resolve_node_for_vmid(vmid)


@mcp.tool()
async def list_containers(node: str | None = None, status_filter: str | None = None) -> dict:
    """List all LXC containers across the cluster or on a specific node.

    Args:
        node: Filter to a specific node. None for all nodes.
        status_filter: Filter by status - 'running', 'stopped', or None for all.
    """
    try:
        client = get_client()
        if node:
            validate_node_name(node)
            client.validate_node(node)
        resources = await client.api_call(client.api.cluster.resources.get, type="vm")
        cts = [r for r in resources if r.get("type") == "lxc"]
        if node:
            cts = [c for c in cts if c.get("node") == node]
        if status_filter:
            cts = [c for c in cts if c.get("status") == status_filter]
        formatted = [format_container_summary(c) for c in cts]
        return {"status": "success", "containers": formatted, "total": len(formatted)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_container_status(vmid: int, node: str | None = None) -> dict:
    """Get detailed status of a specific LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        data = await client.api_call(client.api.nodes(node).lxc(vmid).status.current.get)
        return {"status": "success", "vmid": vmid, "node": node, "data": data}
    except Exception as e:
        return format_error_response(e, suggestion="Use list_containers to see available containers.")


@mcp.tool()
async def get_container_config(vmid: int, node: str | None = None) -> dict:
    """Get full configuration of an LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        data = await client.api_call(client.api.nodes(node).lxc(vmid).config.get)
        return {"status": "success", "vmid": vmid, "node": node, "config": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def start_container(vmid: int, node: str | None = None) -> dict:
    """Start a stopped LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("start_container", vmid=vmid, node=node)
        logger.info("Starting container %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).status.start.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def stop_container(vmid: int, node: str | None = None) -> dict:
    """Stop an LXC container immediately.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("stop_container", vmid=vmid, node=node)
        logger.warning("Stopping container %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).status.stop.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def shutdown_container(vmid: int, node: str | None = None, timeout: int = 60) -> dict:
    """Graceful shutdown of an LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
        timeout: Timeout in seconds (default 60).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("shutdown_container", vmid=vmid, node=node)
        logger.info("Graceful shutdown of container %d on %s", vmid, node)
        upid = await client.api_call(
            client.api.nodes(node).lxc(vmid).status.shutdown.post, timeout=timeout
        )
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def reboot_container(vmid: int, node: str | None = None) -> dict:
    """Reboot an LXC container.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("reboot_container", vmid=vmid, node=node)
        logger.info("Rebooting container %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).status.reboot.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def clone_container(
    vmid: int, newid: int, name: str, node: str | None = None,
    full: bool = True, target_node: str | None = None,
) -> dict:
    """Clone an LXC container.

    Args:
        vmid: Source container ID.
        newid: New VMID for the clone.
        name: Hostname for the clone.
        node: Source node. Auto-detected if omitted.
        full: Full clone (True) or linked (False).
        target_node: Destination node (optional).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_vmid(newid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("clone_container", vmid=vmid, newid=newid, name=name)
        kwargs = {"newid": newid, "hostname": name, "full": 1 if full else 0}
        if target_node:
            kwargs["target"] = target_node
        logger.info("Cloning container %d to %d on %s", vmid, newid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).clone.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def migrate_container(
    vmid: int, target_node: str, node: str | None = None,
    online: bool = False, restart: bool = True,
) -> dict:
    """Migrate an LXC container to another node.

    Args:
        vmid: The container ID.
        target_node: Destination node.
        node: Source node. Auto-detected if omitted.
        online: Online migration (default False).
        restart: Restart after migration (default True).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("migrate_container", vmid=vmid, target=target_node)
        logger.info("Migrating container %d from %s to %s", vmid, node, target_node)
        upid = await client.api_call(
            client.api.nodes(node).lxc(vmid).migrate.post,
            target=target_node, online=1 if online else 0, restart=1 if restart else 0,
        )
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def create_container(
    node: str, ostemplate: str, hostname: str,
    vmid: int | None = None, password: str | None = None,
    ssh_public_keys: str | None = None, memory: int = 512,
    swap: int = 512, cores: int = 1, rootfs_size: str = "8",
    storage: str = "local-lvm", net_bridge: str = "vmbr0",
    ip_config: str = "dhcp", unprivileged: bool = True,
    start_after_create: bool = False,
) -> dict:
    """Create a new LXC container.

    Args:
        node: Node to create the container on.
        ostemplate: Template path (e.g. 'local:vztmpl/ubuntu-22.04.tar.zst').
        hostname: Container hostname.
        vmid: Specific VMID, or None to auto-assign.
        password: Root password (optional).
        ssh_public_keys: SSH public keys for root (optional).
        memory: RAM in MB (default 512).
        swap: Swap in MB (default 512).
        cores: CPU cores (default 1).
        rootfs_size: Root filesystem size in GB (default '8').
        storage: Storage pool (default 'local-lvm').
        net_bridge: Network bridge (default 'vmbr0').
        ip_config: IP config - 'dhcp' or 'ip=x.x.x.x/xx,gw=x.x.x.x' (default 'dhcp').
        unprivileged: Unprivileged container (default True).
        start_after_create: Start after creation (default False).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        if vmid:
            validate_vmid(vmid)
        if client.is_dry_run:
            return client.dry_run_response("create_container", node=node, hostname=hostname)
        net_value = f"name=eth0,bridge={net_bridge}"
        if ip_config == "dhcp":
            ip_value = "ip=dhcp"
        else:
            ip_value = ip_config
        kwargs = {
            "ostemplate": ostemplate,
            "hostname": hostname,
            "memory": memory,
            "swap": swap,
            "cores": cores,
            "rootfs": f"{storage}:{rootfs_size}",
            "net0": net_value,
            "ipconfig0": ip_value,
            "unprivileged": 1 if unprivileged else 0,
            "start": 1 if start_after_create else 0,
        }
        if vmid:
            kwargs["vmid"] = vmid
        if password:
            kwargs["password"] = password
        if ssh_public_keys:
            kwargs["ssh-public-keys"] = ssh_public_keys
        logger.info("Creating container '%s' on %s", hostname, node)
        upid = await client.api_call(client.api.nodes(node).lxc.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_container(
    vmid: int, node: str | None = None, purge: bool = True,
    force: bool = False, confirm: bool = False,
) -> dict:
    """Permanently delete an LXC container. Set confirm=True to execute.

    Args:
        vmid: The container ID to delete.
        node: The node name. Auto-detected if omitted.
        purge: Remove from all configurations (default True).
        force: Force deletion even if running (default False).
        confirm: Must be True to actually delete.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if not confirm:
            ct_data = await client.api_call(client.api.nodes(node).lxc(vmid).status.current.get)
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will PERMANENTLY DELETE container {vmid} ({ct_data.get('name', 'unnamed')}). "
                    f"This cannot be undone."
                ),
                "action": "Call delete_container again with confirm=True to proceed.",
                "container_info": {"vmid": vmid, "name": ct_data.get("name"), "node": node},
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_container", vmid=vmid, node=node)
        kwargs = {}
        if purge:
            kwargs["purge"] = 1
        if force:
            kwargs["force"] = 1
        logger.warning("DELETING container %d on %s", vmid, node)
        upid = await client.api_call(client.api.nodes(node).lxc(vmid).delete, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def modify_container_config(
    vmid: int, node: str | None = None,
    memory: int | None = None, swap: int | None = None,
    cores: int | None = None, hostname: str | None = None,
    description: str | None = None, onboot: bool | None = None,
    tags: str | None = None, extra_config: str | None = None,
) -> dict:
    """Modify LXC container configuration.

    Args:
        vmid: The container ID.
        node: The node name. Auto-detected if omitted.
        memory: RAM in MB.
        swap: Swap in MB.
        cores: CPU cores.
        hostname: Container hostname.
        description: Description.
        onboot: Start on boot.
        tags: Semicolon-separated tags.
        extra_config: JSON string of additional config key/value pairs.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("modify_container_config", vmid=vmid, node=node)
        kwargs = {}
        if memory is not None:
            kwargs["memory"] = memory
        if swap is not None:
            kwargs["swap"] = swap
        if cores is not None:
            kwargs["cores"] = cores
        if hostname is not None:
            kwargs["hostname"] = hostname
        if description is not None:
            kwargs["description"] = description
        if onboot is not None:
            kwargs["onboot"] = 1 if onboot else 0
        if tags is not None:
            kwargs["tags"] = tags
        if extra_config:
            kwargs.update(json.loads(extra_config))
        if not kwargs:
            return {"status": "error", "error_type": "InvalidParameterError",
                    "message": "No configuration changes specified."}
        logger.info("Modifying container %d config: %s", vmid, list(kwargs.keys()))
        await client.api_call(client.api.nodes(node).lxc(vmid).config.put, **kwargs)
        return {"status": "success", "vmid": vmid, "node": node, "changes": list(kwargs.keys())}
    except json.JSONDecodeError:
        return format_error_response(Exception("extra_config must be valid JSON"))
    except Exception as e:
        return format_error_response(e)
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_container_tools.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/proxmox_mcp/tools/container.py tests/test_container_tools.py
git commit -m "feat: container tools - full LXC lifecycle management (13 tools)"
```

---

## Task 14: Backup & Snapshot Tools (7 tools)

**Files:**
- Modify: `src/proxmox_mcp/tools/backup.py`
- Create: `tests/test_backup_tools.py`

**Step 1: Write tests**

```python
# tests/test_backup_tools.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.backup.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.is_dry_run = False
        client.resolve_node_for_vmid = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


@pytest.mark.asyncio
async def test_create_snapshot(mock_client):
    from proxmox_mcp.tools.backup import create_snapshot
    mock_client.api_call.return_value = "UPID:pve1:snap"
    result = await create_snapshot(vmid=100, snapname="before-upgrade")
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_list_snapshots(mock_client):
    from proxmox_mcp.tools.backup import list_snapshots
    mock_client.api_call.return_value = [
        {"name": "snap1", "description": "test", "snaptime": 1700000000},
    ]
    result = await list_snapshots(vmid=100)
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_rollback_snapshot_requires_confirm(mock_client):
    from proxmox_mcp.tools.backup import rollback_snapshot
    result = await rollback_snapshot(vmid=100, snapname="snap1")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_create_backup(mock_client):
    from proxmox_mcp.tools.backup import create_backup
    mock_client.api_call.return_value = "UPID:pve1:vzdump"
    result = await create_backup(vmid=100)
    assert result["status"] == "submitted"


@pytest.mark.asyncio
async def test_list_backups(mock_client):
    from proxmox_mcp.tools.backup import list_backups
    mock_client.api_call.return_value = [
        {"volid": "local:backup/vm-100.vma.zst", "size": 1073741824},
    ]
    result = await list_backups(node="pve1")
    assert result["status"] == "success"
```

**Step 2: Implement**

```python
# src/proxmox_mcp/tools/backup.py
"""Backup and snapshot management tools."""

import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name
from proxmox_mcp.utils.formatters import format_task_result

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


async def _resolve_node(client, vmid: int, node: str | None) -> str:
    if node:
        validate_node_name(node)
        client.validate_node(node)
        return node
    return await client.resolve_node_for_vmid(vmid)


@mcp.tool()
async def create_snapshot(
    vmid: int, snapname: str, node: str | None = None,
    description: str | None = None, include_vmstate: bool = False,
    vm_type: str = "qemu",
) -> dict:
    """Create a snapshot of a VM or container.

    Args:
        vmid: The VM/CT ID.
        snapname: Name for the snapshot.
        node: The node name. Auto-detected if omitted.
        description: Snapshot description (optional).
        include_vmstate: Include VM RAM state - QEMU only (default False).
        vm_type: 'qemu' for VMs or 'lxc' for containers (default 'qemu').
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("create_snapshot", vmid=vmid, snapname=snapname)
        kwargs = {"snapname": snapname}
        if description:
            kwargs["description"] = description
        if include_vmstate and vm_type == "qemu":
            kwargs["vmstate"] = 1
        api_path = client.api.nodes(node).qemu(vmid) if vm_type == "qemu" else client.api.nodes(node).lxc(vmid)
        logger.info("Creating snapshot '%s' for %s %d", snapname, vm_type, vmid)
        upid = await client.api_call(api_path.snapshot.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def list_snapshots(vmid: int, node: str | None = None, vm_type: str = "qemu") -> dict:
    """List all snapshots of a VM or container.

    Args:
        vmid: The VM/CT ID.
        node: The node name. Auto-detected if omitted.
        vm_type: 'qemu' or 'lxc' (default 'qemu').
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        api_path = client.api.nodes(node).qemu(vmid) if vm_type == "qemu" else client.api.nodes(node).lxc(vmid)
        data = await client.api_call(api_path.snapshot.get)
        return {"status": "success", "vmid": vmid, "node": node, "snapshots": data}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def rollback_snapshot(
    vmid: int, snapname: str, node: str | None = None,
    vm_type: str = "qemu", confirm: bool = False,
) -> dict:
    """Rollback a VM/CT to a snapshot. Set confirm=True to execute.

    Args:
        vmid: The VM/CT ID.
        snapname: The snapshot name to rollback to.
        node: The node name. Auto-detected if omitted.
        vm_type: 'qemu' or 'lxc' (default 'qemu').
        confirm: Must be True to execute the rollback.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        client.check_protected(vmid)
        node = await _resolve_node(client, vmid, node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will rollback {vm_type} {vmid} to snapshot '{snapname}'. Current state will be lost.",
                "action": "Call rollback_snapshot again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("rollback_snapshot", vmid=vmid, snapname=snapname)
        api_path = client.api.nodes(node).qemu(vmid) if vm_type == "qemu" else client.api.nodes(node).lxc(vmid)
        logger.warning("Rolling back %s %d to snapshot '%s'", vm_type, vmid, snapname)
        upid = await client.api_call(api_path.snapshot(snapname).rollback.post)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def delete_snapshot(
    vmid: int, snapname: str, node: str | None = None,
    vm_type: str = "qemu", confirm: bool = False,
) -> dict:
    """Delete a snapshot. Set confirm=True to execute.

    Args:
        vmid: The VM/CT ID.
        snapname: The snapshot name to delete.
        node: The node name. Auto-detected if omitted.
        vm_type: 'qemu' or 'lxc' (default 'qemu').
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete snapshot '{snapname}' from {vm_type} {vmid}.",
                "action": "Call delete_snapshot again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_snapshot", vmid=vmid, snapname=snapname)
        api_path = client.api.nodes(node).qemu(vmid) if vm_type == "qemu" else client.api.nodes(node).lxc(vmid)
        logger.warning("Deleting snapshot '%s' from %s %d", snapname, vm_type, vmid)
        upid = await client.api_call(api_path.snapshot(snapname).delete)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def create_backup(
    vmid: int, node: str | None = None, storage: str = "local",
    mode: str = "snapshot", compress: str = "zstd", notes: str | None = None,
) -> dict:
    """Initiate a vzdump backup of a VM or container.

    Args:
        vmid: The VM/CT ID to backup.
        node: The node name. Auto-detected if omitted.
        storage: Target storage for the backup (default 'local').
        mode: Backup mode - 'snapshot', 'suspend', or 'stop' (default 'snapshot').
        compress: Compression - 'zstd', 'lzo', 'gzip', or 'none' (default 'zstd').
        notes: Backup notes (optional).
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("create_backup", vmid=vmid, storage=storage)
        kwargs = {
            "vmid": vmid,
            "storage": storage,
            "mode": mode,
            "compress": compress,
        }
        if notes:
            kwargs["notes-template"] = notes
        logger.info("Starting backup of VMID %d on %s (mode=%s)", vmid, node, mode)
        upid = await client.api_call(client.api.nodes(node).vzdump.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def list_backups(node: str, storage: str = "local", vmid: int | None = None) -> dict:
    """List available backups in a storage pool.

    Args:
        node: The node name.
        storage: The storage pool (default 'local').
        vmid: Filter backups for a specific VMID (optional).
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        kwargs = {"content": "backup"}
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, **kwargs
        )
        if vmid:
            data = [b for b in data if str(vmid) in b.get("volid", "")]
        return {"status": "success", "node": node, "storage": storage, "backups": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def restore_backup(
    node: str, storage: str, archive: str, vmid: int,
    force: bool = False, confirm: bool = False,
) -> dict:
    """Restore a VM/CT from a backup archive. Set confirm=True to execute.

    Args:
        node: The node to restore onto.
        storage: Target storage for the restored disks.
        archive: The backup archive path/volid.
        vmid: VMID for the restored VM/CT.
        force: Overwrite existing VMID if it exists (default False).
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_node_name(node)
        validate_vmid(vmid)
        client.validate_node(node)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will restore backup '{archive}' as VMID {vmid} on {node}.",
                "action": "Call restore_backup again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("restore_backup", archive=archive, vmid=vmid, node=node)
        # Detect type from archive name
        if "lxc" in archive or "ct" in archive:
            kwargs = {"ostemplate": archive, "vmid": vmid, "storage": storage, "restore": 1}
            if force:
                kwargs["force"] = 1
            logger.warning("Restoring LXC backup %s as VMID %d on %s", archive, vmid, node)
            upid = await client.api_call(client.api.nodes(node).lxc.post, **kwargs)
        else:
            kwargs = {"archive": archive, "vmid": vmid, "storage": storage}
            if force:
                kwargs["force"] = 1
            logger.warning("Restoring QEMU backup %s as VMID %d on %s", archive, vmid, node)
            upid = await client.api_call(client.api.nodes(node).qemu.post, **kwargs)
        return format_task_result({"data": upid})
    except Exception as e:
        return format_error_response(e)
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_backup_tools.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/proxmox_mcp/tools/backup.py tests/test_backup_tools.py
git commit -m "feat: backup & snapshot tools - create, list, rollback, delete, backup, restore"
```

---

## Task 15: Network Tools (3 tools)

**Files:**
- Modify: `src/proxmox_mcp/tools/network.py`

**Step 1: Implement**

```python
# src/proxmox_mcp/tools/network.py
"""Network and firewall management tools."""

import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.validators import validate_vmid, validate_node_name

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


async def _resolve_node(client, vmid: int, node: str | None) -> str:
    if node:
        validate_node_name(node)
        client.validate_node(node)
        return node
    return await client.resolve_node_for_vmid(vmid)


@mcp.tool()
async def get_node_firewall_rules(node: str) -> dict:
    """List firewall rules configured on a node.

    Args:
        node: The node name.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        data = await client.api_call(client.api.nodes(node).firewall.rules.get)
        return {"status": "success", "node": node, "rules": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_vm_firewall_rules(vmid: int, node: str | None = None) -> dict:
    """List firewall rules for a specific VM or container.

    Args:
        vmid: The VM/CT ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        # Try QEMU first, fall back to LXC
        try:
            data = await client.api_call(client.api.nodes(node).qemu(vmid).firewall.rules.get)
        except Exception:
            data = await client.api_call(client.api.nodes(node).lxc(vmid).firewall.rules.get)
        return {"status": "success", "vmid": vmid, "node": node, "rules": data, "total": len(data)}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def get_vm_interfaces(vmid: int, node: str | None = None) -> dict:
    """Get network interfaces of a running VM or container (requires guest agent for VMs).

    Args:
        vmid: The VM/CT ID.
        node: The node name. Auto-detected if omitted.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        node = await _resolve_node(client, vmid, node)
        # Try QEMU agent first, fall back to LXC interfaces
        try:
            data = await client.api_call(
                client.api.nodes(node).qemu(vmid).agent("network-get-interfaces").get
            )
            interfaces = data.get("result", data)
        except Exception:
            data = await client.api_call(client.api.nodes(node).lxc(vmid).interfaces.get)
            interfaces = data
        return {"status": "success", "vmid": vmid, "node": node, "interfaces": interfaces}
    except Exception as e:
        return format_error_response(e, suggestion="VM must be running. QEMU VMs require the guest agent.")
```

**Step 2: Commit**

```bash
git add src/proxmox_mcp/tools/network.py
git commit -m "feat: network tools - firewall rules and VM interfaces"
```

---

## Task 16: MCP Resources (10 resources)

**Files:**
- Modify: `src/proxmox_mcp/resources/resources.py`

**Step 1: Implement**

```python
# src/proxmox_mcp/resources/resources.py
"""MCP resource definitions exposing Proxmox state."""

import json
import logging
from proxmox_mcp.utils.formatters import format_vm_summary, format_container_summary

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client
    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.resource("proxmox://cluster/status")
async def cluster_status() -> str:
    """Current cluster health, quorum, and node membership."""
    client = get_client()
    data = await client.api_call(client.api.cluster.status.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://cluster/resources")
async def cluster_resources() -> str:
    """All resources (VMs, CTs, nodes, storage) in the cluster."""
    client = get_client()
    data = await client.api_call(client.api.cluster.resources.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://nodes")
async def nodes_list() -> str:
    """All nodes with CPU, memory, and status summary."""
    client = get_client()
    data = await client.api_call(client.api.nodes.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://node/{node}/status")
async def node_status(node: str) -> str:
    """Detailed status for a specific node."""
    client = get_client()
    data = await client.api_call(client.api.nodes(node).status.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://vms")
async def all_vms() -> str:
    """All QEMU VMs across the cluster with status."""
    client = get_client()
    resources = await client.api_call(client.api.cluster.resources.get, type="vm")
    vms = [format_vm_summary(r) for r in resources if r.get("type") == "qemu"]
    return json.dumps(vms, indent=2, default=str)


@mcp.resource("proxmox://containers")
async def all_containers() -> str:
    """All LXC containers across the cluster with status."""
    client = get_client()
    resources = await client.api_call(client.api.cluster.resources.get, type="vm")
    cts = [format_container_summary(r) for r in resources if r.get("type") == "lxc"]
    return json.dumps(cts, indent=2, default=str)


@mcp.resource("proxmox://vm/{vmid}")
async def vm_detail(vmid: int) -> str:
    """Detailed info for a specific VM (config + status)."""
    client = get_client()
    node = await client.resolve_node_for_vmid(vmid)
    status = await client.api_call(client.api.nodes(node).qemu(vmid).status.current.get)
    config = await client.api_call(client.api.nodes(node).qemu(vmid).config.get)
    return json.dumps({"status": status, "config": config, "node": node}, indent=2, default=str)


@mcp.resource("proxmox://container/{vmid}")
async def container_detail(vmid: int) -> str:
    """Detailed info for a specific container (config + status)."""
    client = get_client()
    node = await client.resolve_node_for_vmid(vmid)
    status = await client.api_call(client.api.nodes(node).lxc(vmid).status.current.get)
    config = await client.api_call(client.api.nodes(node).lxc(vmid).config.get)
    return json.dumps({"status": status, "config": config, "node": node}, indent=2, default=str)


@mcp.resource("proxmox://storage")
async def storage_overview() -> str:
    """All storage pools with usage percentages."""
    client = get_client()
    data = await client.api_call(client.api.storage.get)
    return json.dumps(data, indent=2, default=str)


@mcp.resource("proxmox://tasks/recent")
async def recent_tasks() -> str:
    """Last 20 tasks with status and timing."""
    client = get_client()
    nodes = await client.api_call(client.api.nodes.get)
    all_tasks = []
    for n in nodes:
        tasks = await client.api_call(client.api.nodes(n["node"]).tasks.get, limit=20)
        all_tasks.extend(tasks)
    all_tasks.sort(key=lambda t: t.get("starttime", 0), reverse=True)
    return json.dumps(all_tasks[:20], indent=2, default=str)
```

**Step 2: Commit**

```bash
git add src/proxmox_mcp/resources/resources.py
git commit -m "feat: MCP resources - 10 Proxmox state resources"
```

---

## Task 17: MCP Prompts (6 prompts)

**Files:**
- Modify: `src/proxmox_mcp/prompts/prompts.py`

**Step 1: Implement**

```python
# src/proxmox_mcp/prompts/prompts.py
"""MCP prompt templates for common Proxmox workflows."""


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.prompt()
def infrastructure_overview() -> str:
    """Generate a prompt for reviewing the current Proxmox infrastructure."""
    return (
        "Please provide a comprehensive overview of my Proxmox infrastructure:\n"
        "1. Cluster health and quorum status\n"
        "2. Node status (CPU/RAM utilization, uptime)\n"
        "3. VM summary (running vs stopped, resource allocation)\n"
        "4. Container summary\n"
        "5. Storage utilization across all pools\n"
        "6. Any warnings or issues detected\n"
        "Use the available tools to gather this information."
    )


@mcp.prompt()
def capacity_planning() -> str:
    """Generate a prompt for capacity planning analysis."""
    return (
        "Analyze the current Proxmox cluster capacity:\n"
        "1. Gather node resource utilization (CPU, RAM, storage)\n"
        "2. List all VMs and containers with their allocated resources\n"
        "3. Calculate over-commitment ratios for CPU and RAM\n"
        "4. Identify the most and least loaded nodes\n"
        "5. Recommend if additional capacity is needed\n"
        "6. Suggest VM migration opportunities for load balancing."
    )


@mcp.prompt()
def vm_deployment(name: str, purpose: str, os: str = "linux") -> str:
    """Generate a prompt for deploying a new VM with best practices."""
    return (
        f"Help me deploy a new VM with these requirements:\n"
        f"- Name: {name}\n"
        f"- Purpose: {purpose}\n"
        f"- OS: {os}\n"
        "Steps:\n"
        "1. Check available resources across nodes\n"
        "2. Select the best node based on current load\n"
        "3. Get the next available VMID\n"
        "4. Recommend appropriate resource allocation for the purpose\n"
        "5. Check available ISOs or templates\n"
        "6. Create the VM with best-practice configuration\n"
        "7. Verify creation was successful."
    )


@mcp.prompt()
def disaster_recovery_check() -> str:
    """Generate a prompt for disaster recovery readiness assessment."""
    return (
        "Assess the disaster recovery readiness of this Proxmox environment:\n"
        "1. List all VMs and containers with their last backup date\n"
        "2. Identify any VMs/CTs with no recent backups (>7 days)\n"
        "3. Check snapshot status across all VMs\n"
        "4. Review storage availability for backups\n"
        "5. List any backup jobs configured\n"
        "6. Provide recommendations for improving backup coverage."
    )


@mcp.prompt()
def security_audit() -> str:
    """Generate a prompt for a basic security audit of the Proxmox environment."""
    return (
        "Perform a basic security audit of the Proxmox environment:\n"
        "1. List all nodes and their kernel versions\n"
        "2. Review firewall rules on nodes and VMs\n"
        "3. Check for VMs with no firewall enabled\n"
        "4. List privileged containers (potential security risk)\n"
        "5. Review API access tokens and user permissions\n"
        "6. Identify any VMs/CTs exposed to external networks\n"
        "7. Provide security hardening recommendations."
    )


@mcp.prompt()
def troubleshoot_vm(vmid: int) -> str:
    """Generate a prompt for troubleshooting a problematic VM."""
    return (
        f"Troubleshoot VM {vmid}:\n"
        "1. Get current status and any error states\n"
        "2. Review the VM configuration for misconfigurations\n"
        "3. Check resource allocation vs actual usage (RRD data)\n"
        "4. Review recent tasks related to this VM for errors\n"
        "5. Check the node's syslog for relevant entries\n"
        "6. List snapshots and backup history\n"
        "7. Provide diagnosis and recommended actions."
    )
```

**Step 2: Commit**

```bash
git add src/proxmox_mcp/prompts/prompts.py
git commit -m "feat: MCP prompts - 6 workflow templates"
```

---

## Task 18: conftest.py & Integration Test Stubs

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_integration.py`

**Step 1: Implement conftest**

```python
# tests/conftest.py
"""Shared test fixtures for Proxmox MCP tests."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from proxmox_mcp.config import ProxmoxConfig


@pytest.fixture
def mock_config(monkeypatch):
    """Provide a test ProxmoxConfig with safe defaults."""
    monkeypatch.setenv("PROXMOX_HOST", "10.0.0.1")
    monkeypatch.setenv("PROXMOX_TOKEN_NAME", "test@pam!test-token")
    monkeypatch.setenv("PROXMOX_TOKEN_VALUE", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("PROXMOX_PROTECTED_VMIDS", "100,101")
    monkeypatch.setenv("PROXMOX_ALLOWED_NODES", "")
    monkeypatch.setenv("PROXMOX_DRY_RUN", "false")
    return ProxmoxConfig()
```

**Step 2: Implement integration test stubs**

```python
# tests/test_integration.py
"""Integration tests requiring a live Proxmox instance. Skipped by default."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live Proxmox instance")
class TestLiveCluster:
    async def test_cluster_status(self):
        """Test cluster status against real Proxmox."""
        pass

    async def test_list_nodes(self):
        """Test node listing against real Proxmox."""
        pass

    async def test_list_vms(self):
        """Test VM listing against real Proxmox."""
        pass
```

**Step 3: Run the full test suite**

Run: `uv run pytest tests/ -v --ignore=tests/test_integration.py`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/conftest.py tests/test_integration.py
git commit -m "feat: shared test fixtures and integration test stubs"
```

---

## Task 19: Final Verification & README

**Step 1: Run full test suite with coverage**

Run: `uv run pytest tests/ -v --cov=proxmox_mcp --cov-report=term-missing --ignore=tests/test_integration.py`
Expected: All tests PASS, coverage report shown

**Step 2: Run ruff linter**

Run: `uv run ruff check src/ tests/`
Fix any issues.

**Step 3: Verify the server can import without errors**

Run: `PROXMOX_HOST=test PROXMOX_TOKEN_NAME=test@pam!t PROXMOX_TOKEN_VALUE=x uv run python -c "from proxmox_mcp.server import mcp; print(f'Server: {mcp.name}, Tools registered')"`

**Step 4: Commit any fixes, then final commit**

```bash
git add -A && git commit -m "chore: final linting fixes and verification"
```
