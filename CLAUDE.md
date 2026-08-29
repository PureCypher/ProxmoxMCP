# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP (Model Context Protocol) server for Proxmox VE infrastructure management. Exposes 103 tools, 10 resources, and 6 prompts via FastMCP. Python 3.11+, async-first design wrapping the synchronous `proxmoxer` library with `asyncio.to_thread()`.

## Commands

```bash
# Install (dev) — uv-managed repo; the dev group is a [dependency-groups] dev
uv sync --dev

# The test suite may require PROXMOX_* env vars on a bare clone, e.g.:
# export PROXMOX_HOST=dummy PROXMOX_TOKEN_NAME=dummy PROXMOX_TOKEN_VALUE=dummy

# Run server
proxmox-mcp                    # CLI entry point
python -m proxmox_mcp          # Module entry point

# Tests
pytest tests/                                      # All tests
pytest tests/test_vm_tools.py                      # Single file
pytest tests/test_vm_tools.py::test_list_vms       # Single test
pytest tests/ --cov=src/proxmox_mcp --cov-report=html  # With coverage
pytest tests/ -m integration                       # Integration tests (needs live Proxmox)

# Linting & formatting
ruff check src/ tests/         # Lint
ruff check --fix src/ tests/   # Lint + autofix
ruff format src/ tests/        # Format
mypy src/proxmox_mcp           # Type check
```

## Architecture

### Request flow

`FastMCP server` → `@mcp.tool()` decorated async function in `tools/` → `ProxmoxClient.api_call()` → `asyncio.to_thread(proxmoxer)` → Proxmox API

### Key modules (`src/proxmox_mcp/`)

- **server.py** — Creates `mcp` (FastMCP) and `proxmox_client` (ProxmoxClient) at module level. Tool/resource/prompt modules import these and register via decorators. Side-effect imports at bottom of file register everything with mcp.
- **config.py** — `ProxmoxConfig(BaseSettings)` loads from `.env`. Uses `model_validator` to parse comma-separated env vars into typed lists (protected_vmids, allowed_nodes).
- **client.py** — `ProxmoxClient` wraps proxmoxer. Key safety methods: `check_protected()`, `validate_node()`, `resolve_node()` (validates + auto-detects node for VMID), `dry_run_response()`. All Proxmox API calls go through `api_call()` which runs sync proxmoxer in a thread.
- **tools/** — 11 domain modules (cluster, node, vm, container, storage, task, backup, network, disk, pci, ssh_tools). Each has local `get_mcp()`/`get_client()` helpers that import from `server.py`.
- **resources/resources.py** — 10 read-only `proxmox://` URI resources returning JSON strings.
- **prompts/prompts.py** — 6 workflow prompt templates.
- **utils/** — `errors.py` (exception hierarchy), `validators.py` (validate_vmid, validate_node_name), `sanitizers.py` (input sanitization for disk/shell params), `formatters.py` (format_vm_summary, format_bytes, etc.)
- **ssh.py** — `SSHExecutor` for remote command execution via paramiko (used by disk tools).

### Conventions

- All tool functions are async, return dicts with `"status": "success"` or `"status": "error"`.
- Errors use `format_error_response()` from `utils/errors.py` for consistent structure.
- Resources return `json.dumps()` strings, not dicts.
- Safety guards (protected VMIDs, node allowlist, dry-run) are enforced in `ProxmoxClient`, not in individual tools.

### Test architecture

Tests mock the server module via a session-scoped autouse fixture in `conftest.py` that injects a mock `mcp` and `proxmox_client` into `sys.modules["proxmox_mcp.server"]` before tool imports. This means:
- Unit tests never need a real Proxmox connection.
- Tool tests patch `get_client()` in the specific tool module and use `AsyncMock` for `api_call`.
- Integration tests are marked with `@pytest.mark.integration`.
- `asyncio_mode = "auto"` is set in pyproject.toml — no need for `@pytest.mark.asyncio`.

## Style

- Ruff: line-length 100, target Python 3.11
- Full type annotations on all public functions
- `pyproject.toml` is the single config file (ruff, pytest, mypy, build all configured there)
