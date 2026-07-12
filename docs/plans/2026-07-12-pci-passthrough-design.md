# PCI Passthrough & Hardware Mapping — Design Document

**Date:** 2026-07-12
**Status:** Approved

## Overview

Adds PCI passthrough tooling to ProxmoxMCP, scoped to whole-device passthrough addressed exclusively through Proxmox's cluster-wide hardware mapping system (not raw PCI IDs, not mediated devices/vGPU). Primary driver: GPU clustering — attaching physical GPUs to VMs in a way that survives the VM landing on a different node.

## Background

Proxmox exposes two ways to reference a PCI device on a VM:

- **Raw host ID** (`hostpci0: 01:00.0`): simple, but the PCI address is node-specific and breaks if the VM migrates or the mapping needs updating.
- **Hardware mapping** (`hostpci0: mapping=gpu0`): a named, cluster-wide alias. Proxmox resolves `gpu0` to the correct physical PCI address per node. This is the mechanism intended for HA-eligible / multi-node passthrough setups, and what this design implements exclusively.

Verified against Proxmox's own API surface (not assumed from the original feature-list prompt):

- `GET /nodes/{node}/hardware/pci` returns `iommugroup` as a native field (along with `id`, `vendor`, `device`, `device_name`, `class`, `subsystem_device`). No SSH/`lspci` scraping is needed — this keeps the feature purely API-based, consistent with `vm.py`/`network.py`, not the SSH pattern in `disk.py`.
- `/cluster/mapping/pci` stores a mapping name plus a `map` array of per-node entries: `{node, path, id, iommu_group, subsystem_id}`.
- `hostpciN` VM config natively accepts `mapping=<mapping-id>[,pcie=<0|1>][,rombar=<0|1>][,x-vga=<0|1>]...` as an alternative to `host=<id>`.

## Explicitly Out of Scope

- Raw PCI-ID assignment (mapping-only, per decision).
- Mediated devices / vGPU (`mdev`) — whole-device passthrough only, per decision. Can be a follow-up once this lands.
- USB passthrough.
- A "list VM's assigned PCI devices" tool — `get_vm_config` (existing) already returns `hostpciN` keys verbatim; no new tool needed.
- IOMMU group *validation* logic (e.g., refusing to map a device whose IOMMU group contains other in-use devices) — the tools surface `iommugroup` in `list_node_pci_devices` output so the caller/LLM can reason about it, but do not enforce grouping rules. Add later if this proves to be a real footgun in practice.

## New Module: `src/proxmox_mcp/tools/pci.py`

Follows the existing per-domain tool module pattern (`get_client()`/`get_mcp()` singleton lookups, `@mcp.tool()` registration, `format_error_response()` on exceptions). Pure API-based — no `SSHExecutor` dependency.

### Tools

| Tool | Endpoint | Behavior |
|---|---|---|
| `list_node_pci_devices(node)` | `GET /nodes/{node}/hardware/pci` | Read-only. `validate_node_name` + `client.validate_node`. No confirm/dry-run needed (non-mutating). |
| `list_pci_mappings()` | `GET /cluster/mapping/pci` | Read-only, cluster-wide, no node param. |
| `create_pci_mapping(mapping_id, node, path, comment=None, confirm=False)` | `POST /cluster/mapping/pci` | Looks up `path` in `list_node_pci_devices(node)` internally to auto-fill `id`/`iommu_group`/`subsystem_id` — caller supplies only node + PCI address, never raw hex IDs. Confirm-gated (returns a preview dict when `confirm=False`); dry-run via `client.dry_run_response`. |
| `add_pci_mapping_target(mapping_id, node, path, confirm=False)` | `PUT /cluster/mapping/pci/{id}` | Fetches the existing mapping's `map` array, appends a new node/path entry (same auto-fill as create), PUTs the full updated array. This is what makes a mapping resolve correctly across multiple nodes. Confirm-gated + dry-run. |
| `delete_pci_mapping(mapping_id, confirm=False)` | `DELETE /cluster/mapping/pci/{id}` | Confirm-gated + dry-run. |
| `assign_pci_device(vmid, slot, mapping_id, node=None, pcie=True, rombar=True, x_vga=False, confirm=False)` | VM config: `hostpci{slot}=mapping=<mapping_id>,pcie=<0\|1>,rombar=<0\|1>,x-vga=<0\|1>` | `slot` validated to the integer range 0–15. Calls `client.check_protected(vmid)` and `client.resolve_node(vmid, node)`. Confirm-gated + dry-run. Deliberately narrow: only mapping-based `hostpciN` values are constructible through this tool, so `hostpciN` stays excluded from `VM_SAFE_CONFIG_KEYS` (that exclusion in `modify_vm_config`'s `extra_config` allowlist was a deliberate security decision — arbitrary `hostpci` strings can pass through arbitrary host devices — and is not touched by this feature). |
| `remove_pci_device(vmid, slot, node=None, confirm=False)` | VM config: `delete=hostpci{slot}` | Same guard set as `assign_pci_device`. |

### New validators (`utils/sanitizers.py`)

Matching the existing style (`validate_snapname`, `validate_storage_id`, etc.):

- `validate_pci_mapping_id(mapping_id: str)` — Proxmox resource-id charset (`^[a-zA-Z0-9_-]+$`, length-bounded).
- `validate_pci_slot(slot: int)` — integer in `[0, 15]`.
- `validate_pci_path(path: str)` — PCI address regex, accepting both short (`01:00.0`) and domain-qualified (`0000:01:00.0`) forms.

### Safety model

Mirrors existing conventions exactly — no new safety mechanism introduced:

- Mutating tools require `confirm=True`; without it, return a `{"status": "confirmation_required", ...}` preview (same shape as `disk.py`/`backup.py` destructive-op tools).
- `client.is_dry_run` short-circuits to `client.dry_run_response(tool_name, **params)` before any mutation.
- `assign_pci_device`/`remove_pci_device` call `client.check_protected(vmid)` — protected VMIDs cannot have hardware attached/detached.
- Node params go through `validate_node_name` + `client.validate_node` (allowlist enforcement).

### Testing

New `tests/test_pci_tools.py`, mirroring the structure of `tests/test_network_tools.py`: mocked `client`/`get_client()`, `AsyncMock` for `api_call`. One test class per tool covering happy path, validation errors (bad slot, bad mapping-id format, bad PCI path), the confirm-gate, and dry-run — matching this repo's `asyncio_mode = "auto"` convention (no `@pytest.mark.asyncio` needed) and AAA structure.

### Registration

`server.py` gains `pci` to its tool-module import block (alphabetical, matching the existing list). `README.md`'s tool count and per-domain breakdown get updated (91 → 98 tools).

## Open Questions For Implementation

None — the API shapes above are confirmed against Proxmox's public documentation. Exact proxmoxer method-chaining syntax (`client.api.cluster.mapping.pci.get()` vs. exact kwarg names for the `map` array in the POST/PUT body) will be nailed down against the live API viewer / proxmoxer's generic chaining behavior during implementation, and locked in by the test suite.
