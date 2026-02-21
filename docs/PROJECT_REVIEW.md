# ProxmoxMCP — Project Review & Implementation Roadmap

**Date:** 2026-02-20
**Branch:** `feature/disk-storage-management`
**Reviewed from:** commit `ac1f0f9` + uncommitted disk management work

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Complete Tool Inventory](#2-complete-tool-inventory)
3. [Resources & Prompts](#3-resources--prompts)
4. [Architecture Analysis](#4-architecture-analysis)
5. [Security Issues](#5-security-issues)
6. [Test Coverage Analysis](#6-test-coverage-analysis)
7. [Code Quality Issues](#7-code-quality-issues)
8. [Configuration Gaps](#8-configuration-gaps)
9. [Developer Experience](#9-developer-experience)
10. [Missing Proxmox API Coverage](#10-missing-proxmox-api-coverage)
11. [Implementation Roadmap](#11-implementation-roadmap)

---

## 1. Project Overview

MCP (Model Context Protocol) server for Proxmox VE infrastructure management. Exposes **65 tools**, **10 resources**, and **6 prompts** via FastMCP. Python 3.11+, async-first design wrapping the synchronous `proxmoxer` library with `asyncio.to_thread()`. Disk management tools use SSH via `paramiko`.

### Tech Stack

| Component | Technology |
|-----------|-----------|
| MCP Framework | FastMCP |
| Proxmox API | proxmoxer |
| SSH Layer | paramiko |
| Config | pydantic-settings (.env) |
| Testing | pytest (asyncio_mode=auto) |
| Linting | ruff, mypy |
| Python | 3.11+ |

---

## 2. Complete Tool Inventory

**65 tools** across 9 domain modules.

> Note: CLAUDE.md currently states "58 tools" — this is outdated after adding disk and storage management tools.

### VM Management — `tools/vm.py` (16 tools)

| Tool | Description |
|------|-------------|
| `list_vms` | List all VMs across the cluster |
| `get_vm_status` | Get VM runtime status |
| `get_vm_config` | Get VM configuration |
| `get_vm_rrd_data` | Get VM performance metrics (RRD) |
| `start_vm` | Start a VM |
| `stop_vm` | Force-stop a VM |
| `shutdown_vm` | Graceful ACPI shutdown |
| `reboot_vm` | Reboot a VM |
| `suspend_vm` | Suspend a VM to RAM |
| `resume_vm` | Resume a suspended VM |
| `reset_vm` | Hard-reset a VM |
| `clone_vm` | Clone a VM (full or linked) |
| `migrate_vm` | Live-migrate a VM to another node |
| `create_vm` | Create a new VM |
| `delete_vm` | Delete a VM (with safety checks) |
| `modify_vm_config` | Modify VM configuration |

### Container Management — `tools/container.py` (12 tools)

| Tool | Description |
|------|-------------|
| `list_containers` | List all LXC containers |
| `get_container_status` | Get container runtime status |
| `get_container_config` | Get container configuration |
| `start_container` | Start a container |
| `stop_container` | Force-stop a container |
| `shutdown_container` | Graceful shutdown |
| `reboot_container` | Reboot a container |
| `clone_container` | Clone a container |
| `migrate_container` | Migrate a container to another node |
| `create_container` | Create a new LXC container |
| `delete_container` | Delete a container (with safety checks) |
| `modify_container_config` | Modify container configuration |

### Storage Management — `tools/storage.py` (7 tools)

| Tool | Description |
|------|-------------|
| `list_storage` | List all storage backends |
| `get_storage_status` | Get storage usage/status |
| `list_storage_content` | List contents of a storage |
| `get_available_isos` | List available ISO images |
| `get_available_templates` | List available CT templates |
| `add_storage` | Register a new storage backend |
| `remove_storage` | Unregister a storage backend |

### Backup & Snapshot — `tools/backup.py` (7 tools)

| Tool | Description |
|------|-------------|
| `create_snapshot` | Create a VM/CT snapshot |
| `list_snapshots` | List snapshots for a VM/CT |
| `rollback_snapshot` | Rollback to a snapshot |
| `delete_snapshot` | Delete a snapshot |
| `create_backup` | Create a vzdump backup |
| `list_backups` | List available backups |
| `restore_backup` | Restore from a backup |

### Node Management — `tools/node.py` (6 tools)

| Tool | Description |
|------|-------------|
| `list_nodes` | List all cluster nodes with status |
| `get_node_status` | Get detailed node status |
| `get_node_services` | List services on a node |
| `get_node_network` | Get network interface info |
| `get_node_storage` | Get local storage info |
| `get_node_syslog` | Read node system log |

### Disk Management — `tools/disk.py` (5 tools, SSH-based)

| Tool | Description |
|------|-------------|
| `list_physical_disks` | List physical block devices on a node |
| `partition_disk` | Create a single partition (GPT/MBR) |
| `format_disk` | Format a partition with ext4/xfs/vfat |
| `create_mount_point` | Mount + fstab entry + optional Proxmox storage registration |
| `unmount_path` | Unmount + remove fstab entry |

### Cluster Management — `tools/cluster.py` (5 tools)

| Tool | Description |
|------|-------------|
| `get_cluster_status` | Get cluster status and quorum |
| `get_cluster_resources` | List all cluster resources |
| `get_cluster_log` | Read cluster log |
| `get_next_vmid` | Get next available VMID |
| `list_pools` | List resource pools |

### Task Management — `tools/task.py` (4 tools)

| Tool | Description |
|------|-------------|
| `list_tasks` | List recent tasks on a node |
| `get_task_status` | Get task status by UPID |
| `get_task_log` | Read task log output |
| `wait_for_task` | Poll until a task completes |

### Network/Firewall — `tools/network.py` (3 tools)

| Tool | Description |
|------|-------------|
| `get_node_firewall_rules` | List node firewall rules |
| `get_vm_firewall_rules` | List VM firewall rules |
| `get_vm_interfaces` | Get VM network interfaces |

---

## 3. Resources & Prompts

### Resources (10)

All resources are read-only and return JSON strings via `proxmox://` URIs.

| URI | Description |
|-----|-------------|
| `proxmox://cluster/status` | Cluster status |
| `proxmox://cluster/resources` | All cluster resources |
| `proxmox://nodes` | Node list |
| `proxmox://node/{node}/status` | Node detail |
| `proxmox://vms` | All VMs |
| `proxmox://containers` | All containers |
| `proxmox://vm/{vmid}` | VM detail |
| `proxmox://container/{vmid}` | Container detail |
| `proxmox://storage` | Storage overview |
| `proxmox://tasks/recent` | Recent tasks |

### Prompts (6)

| Prompt | Parameters | Purpose |
|--------|------------|---------|
| `infrastructure_overview` | None | Full infrastructure summary |
| `capacity_planning` | None | Resource capacity analysis |
| `vm_deployment` | name, purpose, os | VM deployment guide |
| `disaster_recovery_check` | None | DR readiness check |
| `security_audit` | None | Security posture review |
| `troubleshoot_vm` | vmid | VM troubleshooting guide |

---

## 4. Architecture Analysis

### Request Flow

```
MCP Client (Claude, etc.)
    |
    v
FastMCP server (server.py)
    |  @mcp.tool() decorated async function
    v
tools/<domain>.py
    |  validate inputs (validators.py / sanitizers.py)
    |  check_protected() / validate_node() / is_dry_run
    v
ProxmoxClient.api_call()          -- for API tools
    |  asyncio.to_thread(proxmoxer)
    v
Proxmox VE REST API (HTTPS)

SSHExecutor.execute()              -- for disk tools
    |  asyncio.to_thread(paramiko)
    v
Proxmox Node Shell (SSH)
```

### Key Patterns

**Deferred imports** — Every tool module uses `get_client()` / `get_mcp()` helpers to break circular imports between `server.py` and tool modules. This is correct and intentional.

**Async wrapping** — Both `proxmoxer` (sync) and `paramiko` (sync) are wrapped via `asyncio.to_thread()` to maintain the async-first design.

**Safety guards in client** — Three safety mechanisms live in `ProxmoxClient`, not in tools:
- `check_protected(vmid)` — prevents operations on protected VMIDs
- `validate_node(node)` — enforces node allowlist
- `dry_run_response()` — short-circuits all writes when dry-run mode is enabled

**Confirmation gates** — Destructive disk operations require `confirm_destructive=True` to proceed. Without it, they return a preview of what would happen.

### Architecture Issues

#### Issue 1: `_resolve_node` Duplicated 4x

An identical private helper `_resolve_node(client, vmid, node)` is copy-pasted in:
- `tools/vm.py:27`
- `tools/container.py:27`
- `tools/backup.py:26`
- `tools/network.py:25`

**Recommendation:** Extract to `ProxmoxClient` as a method or to a shared utility.

#### Issue 2: `vm_type` Not Validated in backup.py

The `vm_type: str = "qemu"` parameter in backup tools is never validated. Passing `vm_type="invalid"` silently routes to the LXC API path via else-branch logic.

**Recommendation:** Validate `vm_type in {"qemu", "lxc"}` at the top of each backup tool.

#### Issue 3: SSH Routes to Single Host Only

`ssh.py:106` always connects to `self.config.PROXMOX_HOST` regardless of the `node` parameter. In multi-node clusters, disk operations would always execute on the API host, not the target node.

**Recommendation:** Support node-to-IP mapping or DNS-based resolution for multi-node setups.

#### Issue 4: Dead Config — `PROXMOX_MAX_CONCURRENT_TASKS`

`config.py:27` defines `PROXMOX_MAX_CONCURRENT_TASKS: int = 5` but it's never used anywhere in the codebase. Zero references outside config and test files.

**Recommendation:** Either implement concurrency limiting in `api_call()` or remove the dead config.

---

## 5. Security Issues

### Critical

#### S1: `paramiko.AutoAddPolicy()` — MITM Vulnerability
**File:** `ssh.py:40`

Silently accepts any SSH host key, making all SSH connections vulnerable to man-in-the-middle attacks. Particularly severe since the SSH user defaults to `root`.

**Recommendation:** Use `RejectPolicy` with a configurable `known_hosts` file. Add a `PROXMOX_SSH_KNOWN_HOSTS` config field.

#### S2: `extra_config` Blocklist Too Narrow
**Files:** `vm.py:522-524`, `container.py:432-434`

Only blocks `{"vmid", "node", "digest"}`. Allows dangerous keys like `hookscript` (arbitrary script execution), `lock`, `cdrom`, `net0`, `scsi0` to pass through unchecked.

**Recommendation:** Switch to an allowlist of safe modifiable keys, or add a comprehensive blocklist including `hookscript`, `lock`, `serial*`, `usb*`, `hostpci*`.

### High

#### S3: SSH Command — UUID Not Quote-Sanitized
**File:** `disk.py` (create_mount_point fstab line construction)

The `device_uuid` from `blkid` output is interpolated into a shell `echo` command. While `blkid` output is trusted, a compromised filesystem could theoretically produce a UUID containing shell metacharacters.

**Recommendation:** Quote-escape UUID values or use `tee` with a heredoc instead of `echo`.

#### S4: `start_vm` Missing `check_protected()`
**File:** `vm.py:124`

`stop_vm` and `delete_vm` check protected status, but `start_vm` does not. Inconsistent safety gate coverage.

### Medium

#### S5: `PROXMOX_VERIFY_SSL` Defaults to `False`
**File:** `config.py:13`

SSL verification disabled by default. Appropriate for homelab self-signed certs but poor for production.

#### S6: SSH Password Fallback Undocumented
**File:** `ssh.py:50`

`PROXMOX_SSH_PASSWORD` falls back to `PROXMOX_PASSWORD` silently. This implicit coupling between API and SSH credentials is not documented in `.env.example`.

#### S7: `snapname` Not Validated
**File:** `backup.py:35`

Snapshot names are passed directly to the API with no format validation. Proxmox requires `[a-zA-Z][a-zA-Z0-9_\-\.]*`.

---

## 6. Test Coverage Analysis

### Test Inventory

| Test File | Count | Module Covered |
|-----------|-------|---------------|
| `test_disk_tools.py` | 35 | disk.py, add_storage, remove_storage |
| `test_sanitizers.py` | 32 | sanitizers.py |
| `test_vm_tools.py` | 16 | vm.py |
| `test_task_tools.py` | 15 | task.py |
| `test_storage_tools.py` | 12 | storage.py (list/get only) |
| `test_cluster_tools.py` | 12 | cluster.py |
| `test_node_tools.py` | 11 | node.py |
| `test_ssh.py` | 9 | ssh.py |
| `test_client.py` | 8 | client.py |
| `test_container_tools.py` | 6 | container.py (partial) |
| `test_config.py` | 6 | config.py |
| `test_backup_tools.py` | 5 | backup.py (partial) |
| `test_formatters.py` | 5 | formatters.py |
| `test_validators.py` | 4 | validators.py |
| `test_errors.py` | 3 | errors.py |
| `test_integration.py` | 3 | Stubs only (`@pytest.mark.skip`) |
| **Total** | **182** | |

### Modules With Zero Tests

| Module | Tools/Items | Impact |
|--------|------------|--------|
| `network.py` | 3 tools | No `test_network_tools.py` exists |
| `resources/resources.py` | 10 resources | No `test_resources.py` exists |
| `prompts/prompts.py` | 6 prompts | No `test_prompts.py` exists |

### Partial Coverage

| Module | Tested | Total | Missing |
|--------|--------|-------|---------|
| `container.py` | 6 of 12 | 50% | `get_container_config`, `shutdown_container`, `reboot_container`, `clone_container`, `migrate_container`, `modify_container_config` |
| `backup.py` | 5 of 7 | 71% | `delete_snapshot`, `restore_backup` |

### Test Architecture Note

The `add_storage` and `remove_storage` tests are in `test_disk_tools.py` instead of `test_storage_tools.py`. This is a file placement issue — they test `storage.py` functions.

---

## 7. Code Quality Issues

### Q1: Logging Inconsistency

~36 logger calls in `cluster.py`, `node.py`, `task.py`, `storage.py` use f-strings (eager evaluation):
```python
logger.error(f"Failed to list storage: {e}")  # BAD: always evaluates
```

Newer modules (`vm.py`, `container.py`, `backup.py`, `disk.py`) correctly use `%` formatting:
```python
logger.info("Starting VM %d on %s", vmid, node)  # GOOD: lazy evaluation
```

**Recommendation:** Standardize on `%` formatting. Enable ruff rule `G` (flake8-logging-format) to enforce.

### Q2: Ruff Configuration Minimal

`pyproject.toml` only configures `target-version` and `line-length`. No rule selection, no ignores, no per-file overrides. Missing recommended rules:
- `G` — flake8-logging-format (catches f-string logging)
- `B` — flake8-bugbear (common bugs)
- `I` — isort (import ordering)
- `UP` — pyupgrade (Python version upgrades)
- `SIM` — simplify (code simplification)

### Q3: No mypy Configuration

No `[tool.mypy]` section in `pyproject.toml`. Running `mypy` uses default (lenient) settings. Missing: `--strict`, `--ignore-missing-imports`, `--no-implicit-optional`.

### Q4: Missing Type Annotation on `api_call`

`client.py:55` — `func` parameter and return type are both untyped:
```python
async def api_call(self, func, *args, **kwargs):  # Should type func and return
```

### Q5: Missing `__all__` in Tool Modules

No tool module exports `__all__`, making the public API surface unclear for tooling and documentation.

---

## 8. Configuration Gaps

### SSH Fields Missing from `.env.example`

The following config fields exist in `config.py` but are absent from `.env.example`:

```bash
PROXMOX_SSH_USER=root          # SSH username (default: root)
PROXMOX_SSH_PORT=22            # SSH port (default: 22)
PROXMOX_SSH_KEY_PATH=          # Path to SSH private key
PROXMOX_SSH_PASSWORD=          # SSH password (falls back to PROXMOX_PASSWORD)
```

Users of disk management tools will get `SSHExecutionError` with no config guidance.

### No API Timeout Configuration

`client.py:34` hardcodes `"timeout": 30`. No environment variable to override for slow networks or large operations.

### Dead Config Field

`PROXMOX_MAX_CONCURRENT_TASKS` is defined and documented in `.env.example` but never used.

---

## 9. Developer Experience

### README — Nearly Empty

`README.md` contains only:
```markdown
# ProxmoxMCP
```

Missing:
- Installation instructions
- Configuration guide
- Tool listing / capabilities overview
- Claude Desktop integration setup
- Usage examples
- Prerequisites (Python 3.11+, Proxmox VE)
- Contributing guidelines

### No CI/CD

No `.github/` directory exists. No GitHub Actions, no automated testing, no lint enforcement, no release automation.

### No Docker Support

No `Dockerfile` or `docker-compose.yml`. Server only runs via direct Python installation.

### docs/ Contains Only Internal Plans

`docs/plans/` has implementation plans but no end-user documentation.

---

## 10. Missing Proxmox API Coverage

### Tier 1 — High Value, Low-Medium Complexity (API-only)

These extend existing patterns and don't require SSH.

| Feature | Proposed Tools | API Endpoint | Complexity |
|---------|---------------|--------------|------------|
| **VM Disk Resize** | `resize_vm_disk` | `PUT /nodes/{node}/qemu/{vmid}/resize` | Low |
| **Cloud-Init Config** | `set_cloudinit_config`, `get_cloudinit_config` | `PUT /nodes/{node}/qemu/{vmid}/config` | Medium |
| **Node Power Mgmt** | `reboot_node`, `shutdown_node` | `POST /nodes/{node}/status` | Low |
| **Template Conversion** | `convert_vm_to_template` | `POST /nodes/{node}/qemu/{vmid}/template` | Low |
| **ISO/Template Download** | `download_to_storage` | `POST /nodes/{node}/storage/{storage}/download-url` | Low |
| **Pool Write Ops** | `create_pool`, `modify_pool`, `delete_pool` | `POST/PUT/DELETE /pools` | Low |
| **Firewall Write Ops** | `add_firewall_rule`, `delete_firewall_rule`, `set_firewall_options` | `POST/DELETE /nodes/{node}/firewall/rules` | Medium |

### Tier 2 — Medium Value, Medium Complexity

| Feature | Proposed Tools | API Endpoint | Complexity |
|---------|---------------|--------------|------------|
| **User Management** | `list_users`, `create_user`, `delete_user`, `set_permissions` | `/access/users`, `/access/acl` | Medium |
| **Backup Scheduling** | `create_backup_job`, `list_backup_jobs`, `delete_backup_job` | `GET/POST/DELETE /cluster/backup` | Medium |
| **HA Management** | `add_ha_resource`, `remove_ha_resource`, `get_ha_status` | `/cluster/ha/resources`, `/cluster/ha/status` | Medium |
| **Certificate/ACME** | `setup_acme`, `order_certificate`, `list_certificates` | `/nodes/{node}/certificates` | Medium |
| **Storage Upload** | `upload_to_storage` | `POST /nodes/{node}/storage/{storage}/upload` | Medium |

### Tier 3 — Advanced Features, Higher Complexity

| Feature | Proposed Tools | Complexity |
|---------|---------------|------------|
| **Ceph Management** | OSD create/remove, pool management, monitor status | High |
| **SDN (Software-Defined Networking)** | VNet, zone, VLAN management | High |
| **Multi-node SSH** | Node-aware SSH routing for disk tools | Medium |
| **Console Proxy** | VNC/SPICE proxy token generation | Medium |

### Tier 4 — Quality, Testing & DevEx

| Item | Impact | Effort |
|------|--------|--------|
| Fix `_resolve_node` duplication | Code quality | Low |
| Add network tool tests (~10 tests) | Coverage | Low |
| Add resource tests (~15 tests) | Coverage | Low |
| Add prompt tests (~8 tests) | Coverage | Low |
| Complete container tool tests (+8 tests) | Coverage | Low |
| Complete backup tool tests (+3 tests) | Coverage | Low |
| Fix logging to use `%` formatting | Consistency | Low |
| Expand ruff rules (G, B, I, UP, SIM) | Code quality | Low |
| Add mypy configuration | Type safety | Low |
| Fix security issues (S1-S7) | Security | Medium |
| Write proper README | Usability | Medium |
| Add GitHub Actions CI | Reliability | Medium |
| Add `.env.example` SSH section | Documentation | Low |
| Add Dockerfile | Deployment | Low |
| Update CLAUDE.md tool count | Accuracy | Trivial |

---

## 11. Implementation Roadmap

### Phase 1: Stabilize (fix existing issues)

**Priority: Immediate**

1. Fix security issues S1 (SSH host key), S2 (extra_config allowlist), S4 (start_vm protected check)
2. Add missing SSH config to `.env.example`
3. Fix `_resolve_node` duplication — extract to shared utility
4. Standardize logging to `%` formatting
5. Add `vm_type` validation in backup tools
6. Update CLAUDE.md tool count to 65
7. Remove or implement `PROXMOX_MAX_CONCURRENT_TASKS`

### Phase 2: Test Coverage

**Priority: High**

1. Add `test_network_tools.py` (~10 tests)
2. Add `test_resources.py` (~15 tests)
3. Add `test_prompts.py` (~8 tests)
4. Complete `test_container_tools.py` (+8 tests for missing tools)
5. Complete `test_backup_tools.py` (+3 tests for delete_snapshot, restore_backup)
6. Move add/remove_storage tests to `test_storage_tools.py`
7. Expand ruff rules and fix findings

### Phase 3: High-Value API Tools

**Priority: High**

1. `resize_vm_disk` — most requested missing feature
2. `convert_vm_to_template` — common workflow
3. `reboot_node` / `shutdown_node` — node management essentials
4. `download_to_storage` — ISO/template download
5. `create_pool` / `modify_pool` / `delete_pool` — pool management

### Phase 4: Infrastructure Management

**Priority: Medium**

1. Firewall write operations
2. Cloud-init configuration tools
3. User and permission management
4. Backup job scheduling
5. HA resource management

### Phase 5: DevEx & Advanced

**Priority: Lower**

1. Write comprehensive README with examples
2. Add GitHub Actions CI/CD pipeline
3. Add Dockerfile for containerized deployment
4. Ceph management (if applicable to user's setup)
5. SDN management (if applicable)
6. Multi-node SSH support

---

## Summary

ProxmoxMCP is a well-architected MCP server with solid foundations (async design, safety guards, input sanitization). The recent disk management addition proves the architecture extends cleanly to SSH-based operations.

**Key numbers:**
- 65 tools, 10 resources, 6 prompts
- 182 tests across 16 test files
- 3 modules with zero test coverage
- 7 security issues identified (1 critical, 1 high, 5 medium)
- ~25 additional Proxmox API features that could be implemented
- README, CI/CD, and Docker support are absent

The project has a strong core. The recommended path is: stabilize (security fixes, consistency) → test coverage → new API tools → DevEx improvements.
