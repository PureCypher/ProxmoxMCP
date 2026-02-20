# Proxmox VE MCP Server — Design Document

**Date:** 2026-02-20
**Status:** Approved

## Overview

A production-grade MCP server for Proxmox Virtual Environment using the Python MCP SDK (`FastMCP`). Exposes Proxmox infrastructure management as MCP tools, resources, and prompts for AI agents.

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| MCP SDK | `mcp[cli]` — `FastMCP` high-level API, `json_response=True` |
| Proxmox Client | `proxmoxer` with `requests` backend |
| Async Strategy | `asyncio.to_thread()` wrapping synchronous proxmoxer calls |
| Transport | STDIO (primary) + Streamable HTTP (optional) |
| Config | Environment variables via `.env` + `pydantic-settings` v2 |
| Packaging | `pyproject.toml` with `uv` and `hatchling` |

## Project Structure

```
proxmox-mcp-server/
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/
│   └── proxmox_mcp/
│       ├── __init__.py
│       ├── server.py              # FastMCP server + entry point
│       ├── config.py              # Pydantic settings
│       ├── client.py              # ProxmoxClient wrapper
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── vm.py              # QEMU/KVM VM management (15 tools)
│       │   ├── container.py       # LXC container management (13 tools)
│       │   ├── node.py            # Node status & management (6 tools)
│       │   ├── storage.py         # Storage management (5 tools)
│       │   ├── backup.py          # Backup & snapshot (7 tools)
│       │   ├── cluster.py         # Cluster operations (5 tools)
│       │   ├── network.py         # Network/firewall (3 tools)
│       │   └── task.py            # Task tracking (4 tools)
│       ├── resources/
│       │   ├── __init__.py
│       │   └── resources.py       # 10 MCP resource definitions
│       ├── prompts/
│       │   ├── __init__.py
│       │   └── prompts.py         # 6 MCP prompt templates
│       └── utils/
│           ├── __init__.py
│           ├── formatters.py      # Response formatting helpers
│           ├── validators.py      # Input validation
│           └── errors.py          # Custom exception hierarchy
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_vm_tools.py
    ├── test_container_tools.py
    ├── test_node_tools.py
    └── test_integration.py
```

## Key Design Decisions

### 1. Async Strategy: `asyncio.to_thread()`

Proxmoxer is synchronous. All tool functions are `async def` and wrap proxmoxer calls with `asyncio.to_thread()`. This is simple, uses proxmoxer as-is, and avoids blocking the event loop.

### 2. No Reconnection Logic

Proxmoxer with API tokens is stateless (token in every request header). No session reconnection needed. A `test_connection()` method calls `GET /version` for reachability checks. Password auth ticket renewal is handled internally by proxmoxer.

### 3. Config Parsing

`PROXMOX_PROTECTED_VMIDS` and `PROXMOX_ALLOWED_NODES` arrive as comma-separated env var strings. Pydantic `@field_validator` parses them into `list[int]` and `list[str]`. Uses pydantic-settings v2 `model_config = SettingsConfigDict(env_file=".env")`.

### 4. modify_vm_config / modify_container_config

Explicit typed params for common fields: `memory`, `cores`, `sockets`, `name`, `description`, `balloon`, `cpu_type`, `onboot`, `tags`. Plus `extra_config: str | None` accepting JSON for anything else.

### 5. Connection Error Naming

Custom exception named `ProxmoxConnectionError` to avoid shadowing Python's built-in `ConnectionError`.

### 6. Safety Check Order

Every write operation:
1. Input validation (VMID range, node name format)
2. Protected VMID check
3. Node allowlist check
4. Dry-run check
5. Confirmation check (DANGEROUS ops only)
6. Execute

### 7. Destructive Operation Tiers

- **DANGEROUS** (`delete_vm`, `delete_container`, `rollback_snapshot`, `delete_snapshot`, `restore_backup`): Require `confirm=True` parameter.
- **Destructive** (`stop_vm`, `stop_container`, `reset_vm`): Execute directly but respect protected VMIDs and dry-run.
- **Safe**: All read operations and non-destructive writes.

### 8. Response Format

Every tool returns a `dict`:
- Success: `{"status": "success", ...data}`
- Error: `{"status": "error", "error_type": "...", "message": "...", "suggestion": "..."}`
- Dry-run: `{"status": "dry_run", "action": "...", "params": {...}, "message": "..."}`
- Confirmation needed: `{"status": "confirmation_required", "warning": "...", "action": "...", ...}`

## Tools (58 total)

### VM Management (15 tools)
`list_vms`, `get_vm_status`, `get_vm_config`, `start_vm`, `stop_vm`, `shutdown_vm`, `reboot_vm`, `suspend_vm`, `resume_vm`, `reset_vm`, `clone_vm`, `migrate_vm`, `create_vm`, `delete_vm`, `modify_vm_config`, `get_vm_rrd_data`

### Container Management (13 tools)
`list_containers`, `get_container_status`, `get_container_config`, `start_container`, `stop_container`, `shutdown_container`, `reboot_container`, `clone_container`, `migrate_container`, `create_container`, `delete_container`, `modify_container_config`

### Node Management (6 tools)
`list_nodes`, `get_node_status`, `get_node_services`, `get_node_network`, `get_node_storage`, `get_node_syslog`

### Storage Management (5 tools)
`list_storage`, `get_storage_status`, `list_storage_content`, `get_available_isos`, `get_available_templates`

### Backup & Snapshot (7 tools)
`create_snapshot`, `list_snapshots`, `rollback_snapshot`, `delete_snapshot`, `create_backup`, `list_backups`, `restore_backup`

### Cluster Operations (5 tools)
`get_cluster_status`, `get_cluster_resources`, `get_cluster_log`, `get_next_vmid`, `list_pools`

### Network & Firewall (3 tools)
`get_node_firewall_rules`, `get_vm_firewall_rules`, `get_vm_interfaces`

### Task Tracking (4 tools)
`list_tasks`, `get_task_status`, `get_task_log`, `wait_for_task`

## Resources (10)

`proxmox://cluster/status`, `proxmox://cluster/resources`, `proxmox://nodes`, `proxmox://node/{node}/status`, `proxmox://vms`, `proxmox://containers`, `proxmox://vm/{vmid}`, `proxmox://container/{vmid}`, `proxmox://storage`, `proxmox://tasks/recent`

## Prompts (6)

`infrastructure_overview`, `capacity_planning`, `vm_deployment`, `disaster_recovery_check`, `security_audit`, `troubleshoot_vm`

## Testing Strategy

- Mocked unit tests using `unittest.mock.AsyncMock` for proxmoxer
- Shared fixtures in `conftest.py` (mock client, mock config with protected VMIDs)
- Test files per tool category
- Safety guard tests (protected VMIDs, node allowlist, dry-run, confirmation)
- Error path tests (missing VMs, connection failures, invalid params)
- Integration test stubs with `@pytest.mark.integration`, skipped by default

## Implementation Phases

1. Foundation: `config.py`, `client.py`, `errors.py`, `formatters.py`, `validators.py`, `server.py` skeleton
2. Read-Only Tools: `cluster.py`, `node.py`, `storage.py`, `task.py`
3. VM & Container Tools: `vm.py`, `container.py`
4. Backup & Snapshot Tools: `backup.py`
5. Network Tools: `network.py`
6. Resources & Prompts: `resources.py`, `prompts.py`
7. Tests: Full test suite
8. Documentation: README, `.env.example`, `.gitignore`
