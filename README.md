# ProxmoxMCP

MCP (Model Context Protocol) server for managing Proxmox VE infrastructure through AI assistants like Claude. Exposes **91 tools**, **10 resources**, and **6 prompt templates** via FastMCP.

## Features

- **91 tools** across 9 domains: VMs, containers, storage, networking, backups, cluster, nodes, tasks, and disk management
- **Safety guards**: protected VMIDs, node allowlists, dry-run mode, confirmation prompts for destructive operations
- **Async-first**: all Proxmox API calls run via `asyncio.to_thread()` for non-blocking operation
- **SSH disk management**: partition, format, mount, and unmount physical disks via SSH
- **Structured JSON responses**: consistent `{"status": "success"}` / `{"status": "error"}` format

## Quick Start

### 1. Install

```bash
pip install -e .
```

Or with development dependencies:

```bash
pip install -e ".[dev]"
```

### 2. Configure

Copy `.env.example` to `.env` and set your Proxmox connection details:

```bash
cp .env.example .env
```

Required settings:

```env
PROXMOX_HOST=192.168.1.100
PROXMOX_TOKEN_NAME=root@pam!mcp-token
PROXMOX_TOKEN_VALUE=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 3. Run

```bash
# CLI entry point
proxmox-mcp

# Or as a module
python -m proxmox_mcp
```

### 4. Connect to Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "proxmox": {
      "command": "proxmox-mcp",
      "env": {
        "PROXMOX_HOST": "192.168.1.100",
        "PROXMOX_TOKEN_NAME": "root@pam!mcp-token",
        "PROXMOX_TOKEN_VALUE": "your-token-value"
      }
    }
  }
}
```

## Tool Inventory

### VM Management (20 tools)

| Tool | Description |
|------|-------------|
| `list_vms` | List all QEMU VMs across the cluster |
| `get_vm_status` | Get detailed VM status |
| `get_vm_config` | Get full VM configuration |
| `get_vm_rrd_data` | Get VM performance metrics over time |
| `start_vm` | Start a stopped VM |
| `stop_vm` | Hard stop a VM |
| `shutdown_vm` | Graceful ACPI shutdown |
| `reboot_vm` | Reboot a VM via ACPI |
| `suspend_vm` | Suspend/pause a running VM |
| `resume_vm` | Resume a suspended VM |
| `reset_vm` | Hard reset a VM |
| `clone_vm` | Clone a VM (full or linked) |
| `migrate_vm` | Live-migrate a VM to another node |
| `create_vm` | Create a new QEMU VM |
| `delete_vm` | Permanently delete a VM |
| `resize_vm_disk` | Resize a VM disk |
| `convert_vm_to_template` | Convert a VM to a template |
| `modify_vm_config` | Modify VM configuration |
| `set_vm_cloudinit` | Configure cloud-init settings |
| `regenerate_cloudinit_image` | Regenerate cloud-init drive |

### Container Management (12 tools)

| Tool | Description |
|------|-------------|
| `list_containers` | List all LXC containers |
| `get_container_status` | Get container status |
| `get_container_config` | Get container configuration |
| `start_container` | Start a container |
| `stop_container` | Stop a container |
| `shutdown_container` | Graceful container shutdown |
| `reboot_container` | Reboot a container |
| `clone_container` | Clone a container |
| `migrate_container` | Migrate a container |
| `create_container` | Create a new container |
| `delete_container` | Delete a container |
| `modify_container_config` | Modify container config |

### Cluster & Access Management (17 tools)

| Tool | Description |
|------|-------------|
| `get_cluster_status` | Cluster status and quorum |
| `get_cluster_resources` | All resources across the cluster |
| `get_cluster_log` | Recent cluster log entries |
| `get_next_vmid` | Next available VMID |
| `list_pools` | List resource pools |
| `create_pool` | Create a resource pool |
| `modify_pool` | Modify pool membership |
| `delete_pool` | Delete a resource pool |
| `list_users` | List all users |
| `create_user` | Create a new user |
| `delete_user` | Delete a user |
| `list_roles` | List available roles |
| `set_user_permission` | Set ACL permissions |
| `list_ha_resources` | List HA-managed resources |
| `create_ha_resource` | Add VM/CT to HA management |
| `modify_ha_resource` | Modify HA resource settings |
| `delete_ha_resource` | Remove from HA management |

### Node Management (8 tools)

| Tool | Description |
|------|-------------|
| `list_nodes` | List all cluster nodes |
| `get_node_status` | Detailed node status |
| `get_node_services` | Node system services |
| `get_node_network` | Node network interfaces |
| `get_node_storage` | Node storage backends |
| `get_node_syslog` | Node syslog entries |
| `reboot_node` | Reboot a node |
| `shutdown_node` | Shut down a node |

### Storage Management (8 tools)

| Tool | Description |
|------|-------------|
| `list_storage` | List all storage backends |
| `get_storage_status` | Storage usage details |
| `list_storage_content` | List storage contents |
| `get_available_isos` | List available ISOs |
| `get_available_templates` | List container templates |
| `add_storage` | Register a new storage backend |
| `remove_storage` | Unregister a storage backend |
| `download_to_storage` | Download ISO/template from URL |

### Backup & Snapshot Management (10 tools)

| Tool | Description |
|------|-------------|
| `create_snapshot` | Create a VM/CT snapshot |
| `list_snapshots` | List all snapshots |
| `rollback_snapshot` | Rollback to a snapshot |
| `delete_snapshot` | Delete a snapshot |
| `create_backup` | Start a vzdump backup |
| `list_backups` | List available backups |
| `restore_backup` | Restore from backup |
| `list_backup_jobs` | List scheduled backup jobs |
| `create_backup_job` | Create a backup schedule |
| `delete_backup_job` | Delete a backup schedule |

### Network & Firewall (7 tools)

| Tool | Description |
|------|-------------|
| `get_node_firewall_rules` | List node firewall rules |
| `get_vm_firewall_rules` | List VM/CT firewall rules |
| `get_vm_interfaces` | Get VM/CT network interfaces |
| `create_node_firewall_rule` | Create a node firewall rule |
| `delete_node_firewall_rule` | Delete a node firewall rule |
| `create_vm_firewall_rule` | Create a VM/CT firewall rule |
| `delete_vm_firewall_rule` | Delete a VM/CT firewall rule |

### Task Tracking (4 tools)

| Tool | Description |
|------|-------------|
| `list_tasks` | List recent tasks |
| `get_task_status` | Get task status by UPID |
| `get_task_log` | Get task log output |
| `wait_for_task` | Wait for task completion |

### Disk Management (5 tools, SSH-based)

| Tool | Description |
|------|-------------|
| `list_physical_disks` | List physical disks on a node |
| `partition_disk` | Create partitions on a disk |
| `format_disk` | Format a partition |
| `create_mount_point` | Mount a filesystem with fstab |
| `unmount_path` | Unmount and clean up fstab |

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXMOX_HOST` | *required* | Proxmox host IP or hostname |
| `PROXMOX_PORT` | `8006` | API port |
| `PROXMOX_VERIFY_SSL` | `false` | Verify SSL certificates |
| `PROXMOX_TOKEN_NAME` | | API token name (e.g. `root@pam!token`) |
| `PROXMOX_TOKEN_VALUE` | | API token value |
| `PROXMOX_USER` | | Username (fallback auth) |
| `PROXMOX_PASSWORD` | | Password (fallback auth) |
| `PROXMOX_DRY_RUN` | `false` | Simulate write operations |
| `PROXMOX_PROTECTED_VMIDS` | | Comma-separated VMIDs to protect from modification |
| `PROXMOX_ALLOWED_NODES` | | Comma-separated node allowlist (empty = all) |
| `PROXMOX_SSH_USER` | `root` | SSH user for disk tools |
| `PROXMOX_SSH_PORT` | `22` | SSH port |
| `PROXMOX_SSH_KEY_PATH` | | Path to SSH private key |
| `PROXMOX_SSH_HOST_KEY_CHECKING` | `true` | Verify SSH host keys |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `streamable-http` |
| `MCP_HTTP_PORT` | `3001` | HTTP port (when using streamable-http) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Safety Features

- **Protected VMIDs**: VMs in `PROXMOX_PROTECTED_VMIDS` cannot be modified, stopped, or deleted
- **Node allowlist**: When `PROXMOX_ALLOWED_NODES` is set, operations are restricted to listed nodes
- **Dry-run mode**: Set `PROXMOX_DRY_RUN=true` to simulate all write operations
- **Confirmation prompts**: Destructive operations (delete, rollback, restore) require `confirm=True`
- **Input validation**: VMIDs, node names, snapshot names, and storage IDs are validated against injection
- **Config key allowlists**: `modify_vm_config` blocks dangerous keys like `hookscript` and `hostpci`
- **SSH host key verification**: Enabled by default for disk management operations

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_vm_tools.py

# Run with coverage
pytest tests/ --cov=src/proxmox_mcp --cov-report=html

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/proxmox_mcp
```

## Architecture

```
FastMCP server
  -> @mcp.tool() async function (tools/)
    -> ProxmoxClient.api_call()
      -> asyncio.to_thread(proxmoxer)
        -> Proxmox REST API
```

- **9 tool modules**: `vm`, `container`, `cluster`, `node`, `storage`, `backup`, `network`, `task`, `disk`
- **ProxmoxClient** (`client.py`): wraps proxmoxer with safety guards and async support
- **Config** (`config.py`): pydantic-settings loading from `.env`
- **Resources**: 10 read-only `proxmox://` URI resources returning cluster state as JSON
- **Prompts**: 6 workflow templates for common operations

## License

MIT
