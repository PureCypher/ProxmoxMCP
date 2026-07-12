# PCI Passthrough & Hardware Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 7 MCP tools for PCI passthrough via Proxmox's cluster-wide hardware mapping system (GPU-clustering use case), plus 3 new input validators, following this repo's existing per-domain tool-module pattern exactly.

**Architecture:** A new pure-API tool module `src/proxmox_mcp/tools/pci.py` (no SSH), registered in `server.py` alongside the other 10 domain modules. Two read-only discovery tools, three mutating cluster-mapping CRUD tools, and two mutating VM-attachment tools — all following the existing `validate → check_protected/resolve_node → confirm-gate → dry-run → api_call` pipeline used throughout `network.py`/`cluster.py`/`vm.py`.

**Tech Stack:** Python 3.11+, `proxmoxer` (via `ProxmoxClient.api_call`), `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`), `ruff`, `mypy`.

## Global Constraints

- Follow the existing tool-module pattern exactly: module-level `get_client()`/`get_mcp()` deferred-import helpers (typed per the `TYPE_CHECKING` convention already used across all 10 tool modules), `mcp = get_mcp()` at module level, `@mcp.tool()` decorator per tool, `try/except Exception: return format_error_response(e)` in every tool body.
- Every mutating tool requires `confirm: bool = False` and returns `{"status": "confirmation_required", ...}` when not confirmed — same shape as `network.py`'s `delete_node_firewall_rule`.
- Every mutating tool checks `client.is_dry_run` and returns `client.dry_run_response(tool_name, **params)` before calling the API — same as every other tool in this codebase.
- `assign_pci_device`/`remove_pci_device` call `client.check_protected(vmid)` (VM-touching operations).
- No SSH — this module only uses `client.api_call`, never `SSHExecutor`.
- Ruff line-length 100, full type annotations, `%`-style logging (never f-string in `logger.*` calls).
- Run `.venv/bin/pytest tests/ -q`, `.venv/bin/ruff check src/ tests/`, and `.venv/bin/mypy src/proxmox_mcp` after every task; all three must be clean before committing.

---

## File Structure

- Modify: `src/proxmox_mcp/utils/sanitizers.py` — add `PCI_MAPPING_ID_RE`, `PCI_PATH_RE`, `validate_pci_mapping_id`, `validate_pci_path`, `validate_pci_slot`.
- Modify: `tests/test_sanitizers.py` — add `TestPciMappingId`, `TestPciPath`, `TestPciSlot`.
- Create: `src/proxmox_mcp/tools/pci.py` — the new module (7 `@mcp.tool()` functions + 2 private helpers).
- Create: `tests/test_pci_tools.py` — full tool test suite.
- Modify: `src/proxmox_mcp/server.py` — add `pci` to the tool-module import block.
- Modify: `README.md` — tool count 91→98, new "PCI Passthrough (7 tools)" section.

---

## Task 1: PCI validators

**Files:**
- Modify: `src/proxmox_mcp/utils/sanitizers.py`
- Test: `tests/test_sanitizers.py`

**Interfaces:**
- Produces: `validate_pci_mapping_id(mapping_id: str) -> None` (raises `InvalidParameterError`), `validate_pci_path(path: str) -> None` (raises `InvalidParameterError`), `validate_pci_slot(slot: int) -> None` (raises `InvalidParameterError`). All three importable from `proxmox_mcp.utils.sanitizers`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sanitizers.py`, in the imports block at the top:

```python
from proxmox_mcp.utils.sanitizers import (
    check_shell_injection,
    validate_device_path,
    validate_filesystem,
    validate_label,
    validate_mkfs_options,
    validate_mount_options,
    validate_mount_path,
    validate_partition_table,
    validate_pci_mapping_id,
    validate_pci_path,
    validate_pci_slot,
    validate_snapname,
    validate_storage_id,
    validate_uuid,
)
```

Append at the end of the file:

```python
# --- validate_pci_mapping_id ---


class TestPciMappingId:
    @pytest.mark.parametrize("good_id", ["gpu0", "gpu-nvidia-0", "GPU_0"])
    def test_valid_mapping_id_passes(self, good_id):
        validate_pci_mapping_id(good_id)

    @pytest.mark.parametrize(
        "bad_id",
        ["0gpu", "gpu;rm -rf", "", "a" * 65, "gpu 0", "gpu$(whoami)"],
    )
    def test_rejects_invalid_mapping_id(self, bad_id):
        with pytest.raises(InvalidParameterError):
            validate_pci_mapping_id(bad_id)


# --- validate_pci_path ---


class TestPciPath:
    @pytest.mark.parametrize("good_path", ["01:00.0", "0000:01:00.0", "3b:00.1", "ff:1f.7"])
    def test_valid_path_passes(self, good_path):
        validate_pci_path(good_path)

    @pytest.mark.parametrize(
        "bad_path",
        ["01:00", "gpu0", "01:00.0; rm -rf /", "0000:01:00", "01:00.g", ""],
    )
    def test_rejects_invalid_path(self, bad_path):
        with pytest.raises(InvalidParameterError):
            validate_pci_path(bad_path)


# --- validate_pci_slot ---


class TestPciSlot:
    @pytest.mark.parametrize("slot", [0, 1, 8, 15])
    def test_valid_slot_passes(self, slot):
        validate_pci_slot(slot)

    @pytest.mark.parametrize("slot", [-1, 16, 100, -100])
    def test_rejects_out_of_range_slot(self, slot):
        with pytest.raises(InvalidParameterError):
            validate_pci_slot(slot)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sanitizers.py -v -k Pci`
Expected: FAIL with `ImportError: cannot import name 'validate_pci_mapping_id'`

- [ ] **Step 3: Implement the validators**

In `src/proxmox_mcp/utils/sanitizers.py`, add these two regex constants right after the existing `SNAPNAME_RE` definition (around line 89-90):

```python
PCI_MAPPING_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]{0,63}$")
PCI_PATH_RE = re.compile(r"^(?:[0-9a-fA-F]{4}:)?[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]$")
```

Then add these three functions at the end of the file, after `validate_script_interpreter`:

```python
def validate_pci_mapping_id(mapping_id: str) -> None:
    """Validate a Proxmox PCI hardware mapping identifier."""
    check_shell_injection(mapping_id, "mapping_id")
    if not PCI_MAPPING_ID_RE.match(mapping_id):
        raise InvalidParameterError(
            f"Mapping ID '{mapping_id}' is invalid. "
            f"Must start with a letter, contain only alphanumeric/hyphens/underscores, "
            f"and be at most 64 characters."
        )


def validate_pci_path(path: str) -> None:
    """Validate a PCI bus address (e.g. '01:00.0' or '0000:01:00.0')."""
    check_shell_injection(path, "path")
    if not PCI_PATH_RE.match(path):
        raise InvalidParameterError(
            f"PCI path '{path}' is invalid. "
            f"Must be a bus address like '01:00.0' or '0000:01:00.0'."
        )


def validate_pci_slot(slot: int) -> None:
    """Validate a hostpci slot number (0-15)."""
    if not 0 <= slot <= 15:
        raise InvalidParameterError(
            f"PCI slot {slot} is invalid. Must be between 0 and 15 (hostpci0-hostpci15)."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sanitizers.py -v -k Pci`
Expected: PASS, 14 tests

- [ ] **Step 5: Lint and type-check**

Run: `.venv/bin/ruff check src/proxmox_mcp/utils/sanitizers.py tests/test_sanitizers.py && .venv/bin/mypy src/proxmox_mcp/utils/sanitizers.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/proxmox_mcp/utils/sanitizers.py tests/test_sanitizers.py
git commit -m "feat: add PCI mapping/path/slot validators"
```

---

## Task 2: `pci.py` module skeleton + read-only discovery tools

**Files:**
- Create: `src/proxmox_mcp/tools/pci.py`
- Test: `tests/test_pci_tools.py`

**Interfaces:**
- Consumes: `ProxmoxClient.api_call(func, *args, **kwargs) -> T` (`client.py`), `ProxmoxClient.validate_node(node: str) -> None`, `validate_node_name(node: str) -> None` (`utils/validators.py`), `format_error_response(e: Exception) -> dict` (`utils/errors.py`).
- Produces: `get_client() -> "ProxmoxClient"`, `get_mcp() -> "FastMCP"`, `list_node_pci_devices(node: str) -> dict`, `list_pci_mappings() -> dict`. These are consumed by later tasks in this same module (Tasks 3-5 add more tools to this file) and by Task 6 (`server.py` import).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pci_tools.py`:

```python
"""Tests for PCI passthrough and hardware mapping tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_client():
    with patch("proxmox_mcp.tools.pci.get_client") as mock_get:
        client = MagicMock()
        client.config.PROXMOX_ALLOWED_NODES = []
        client.config.PROXMOX_PROTECTED_VMIDS = []
        client.is_dry_run = False
        client.resolve_node = AsyncMock(return_value="pve1")
        mock_get.return_value = client
        yield client


SAMPLE_DEVICE = {
    "id": "0000:01:00.0",
    "vendor": "0x10de",
    "device": "0x1eb8",
    "device_name": "TU104GL [Tesla T4]",
    "iommugroup": 45,
    "class": "0x030200",
}


# --- list_node_pci_devices ---


@pytest.mark.asyncio
async def test_list_node_pci_devices(mock_client):
    from proxmox_mcp.tools.pci import list_node_pci_devices

    mock_client.api_call = AsyncMock(return_value=[SAMPLE_DEVICE])
    result = await list_node_pci_devices(node="pve1")

    assert result["status"] == "success"
    assert result["node"] == "pve1"
    assert result["total"] == 1
    assert result["devices"] == [SAMPLE_DEVICE]


@pytest.mark.asyncio
async def test_list_node_pci_devices_error(mock_client):
    from proxmox_mcp.tools.pci import list_node_pci_devices

    mock_client.api_call = AsyncMock(side_effect=Exception("node unreachable"))
    result = await list_node_pci_devices(node="pve1")

    assert result["status"] == "error"


# --- list_pci_mappings ---


@pytest.mark.asyncio
async def test_list_pci_mappings(mock_client):
    from proxmox_mcp.tools.pci import list_pci_mappings

    mappings = [{"id": "gpu0", "map": ["node=pve1,path=0000:01:00.0"]}]
    mock_client.api_call = AsyncMock(return_value=mappings)
    result = await list_pci_mappings()

    assert result["status"] == "success"
    assert result["total"] == 1
    assert result["mappings"] == mappings


@pytest.mark.asyncio
async def test_list_pci_mappings_empty(mock_client):
    from proxmox_mcp.tools.pci import list_pci_mappings

    mock_client.api_call = AsyncMock(return_value=[])
    result = await list_pci_mappings()

    assert result["status"] == "success"
    assert result["total"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pci_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'proxmox_mcp.tools.pci'`

- [ ] **Step 3: Create the module**

Create `src/proxmox_mcp/tools/pci.py`:

```python
"""PCI passthrough and cluster hardware mapping tools for Proxmox VE."""

import logging
from typing import TYPE_CHECKING

from proxmox_mcp.utils.errors import InvalidParameterError, format_error_response
from proxmox_mcp.utils.sanitizers import (
    validate_pci_mapping_id,
    validate_pci_path,
    validate_pci_slot,
)
from proxmox_mcp.utils.validators import validate_node_name, validate_vmid

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from proxmox_mcp.client import ProxmoxClient

logger = logging.getLogger("proxmox-mcp")


def get_client() -> "ProxmoxClient":
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp() -> "FastMCP":
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()


@mcp.tool()
async def list_node_pci_devices(node: str) -> dict:
    """List PCI devices on a node, including IOMMU group (needed for passthrough).

    Args:
        node: The node name.
    """
    try:
        client = get_client()
        validate_node_name(node)
        client.validate_node(node)
        devices = await client.api_call(client.api.nodes(node).hardware.pci.get)
        return {"status": "success", "node": node, "total": len(devices), "devices": devices}
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def list_pci_mappings() -> dict:
    """List cluster-wide PCI hardware mappings."""
    try:
        client = get_client()
        mappings = await client.api_call(client.api.cluster.mapping.pci.get)
        return {"status": "success", "total": len(mappings), "mappings": mappings}
    except Exception as e:
        return format_error_response(e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pci_tools.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Lint and type-check**

Run: `.venv/bin/ruff check src/proxmox_mcp/tools/pci.py tests/test_pci_tools.py && .venv/bin/mypy src/proxmox_mcp/tools/pci.py`
Expected: clean (module isn't registered in `server.py` yet, so `mypy` checking it standalone will show the same pre-existing `server.py:12` `PROXMOX_HOST` pydantic-settings false positive as every other tool module — that's expected and out of scope, same as the rest of the codebase)

- [ ] **Step 6: Commit**

```bash
git add src/proxmox_mcp/tools/pci.py tests/test_pci_tools.py
git commit -m "feat: add PCI device and mapping discovery tools"
```

---

## Task 3: Hardware mapping creation (`create_pci_mapping`, `add_pci_mapping_target`)

**Files:**
- Modify: `src/proxmox_mcp/tools/pci.py`
- Test: `tests/test_pci_tools.py`

**Interfaces:**
- Consumes: `list_node_pci_devices` internals (device shape: `{"id": "<bus-address>", "vendor": "0x....", "device": "0x....", "iommugroup": <int>}`), `client.api_call`, `validate_pci_mapping_id`, `validate_node_name`, `validate_pci_path` (all from Task 1/2).
- Produces: `_build_map_entry(node: str, path: str, device: dict) -> str` and `_lookup_pci_device(client, node: str, path: str) -> dict` (private helpers — Task 4/5 do not need them, but keep them in this module for cohesion). `create_pci_mapping(mapping_id: str, node: str, path: str, comment: str | None = None, confirm: bool = False) -> dict`, `add_pci_mapping_target(mapping_id: str, node: str, path: str, confirm: bool = False) -> dict`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pci_tools.py`:

```python
# --- create_pci_mapping ---


@pytest.mark.asyncio
async def test_create_pci_mapping_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    result = await create_pci_mapping(mapping_id="gpu0", node="pve1", path="01:00.0")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_create_pci_mapping_confirmed(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.api_call = AsyncMock(side_effect=[[SAMPLE_DEVICE], None])
    result = await create_pci_mapping(
        mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True
    )

    assert result["status"] == "success"
    assert result["mapping_id"] == "gpu0"
    assert "node=pve1" in result["map_entry"]
    assert "path=01:00.0" in result["map_entry"]
    assert "id=10de:1eb8" in result["map_entry"]
    assert "iommu-group=45" in result["map_entry"]


@pytest.mark.asyncio
async def test_create_pci_mapping_device_not_found(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.api_call = AsyncMock(return_value=[])
    result = await create_pci_mapping(
        mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True
    )

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_create_pci_mapping_dry_run(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await create_pci_mapping(
        mapping_id="gpu0", node="pve1", path="01:00.0", confirm=True
    )
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_create_pci_mapping_invalid_id(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    result = await create_pci_mapping(
        mapping_id="0bad", node="pve1", path="01:00.0", confirm=True
    )
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_create_pci_mapping_with_comment(mock_client):
    from proxmox_mcp.tools.pci import create_pci_mapping

    mock_client.api_call = AsyncMock(side_effect=[[SAMPLE_DEVICE], None])
    result = await create_pci_mapping(
        mapping_id="gpu0", node="pve1", path="01:00.0", comment="Tesla T4", confirm=True
    )
    assert result["status"] == "success"
    post_call_kwargs = mock_client.api_call.call_args_list[1].kwargs
    assert post_call_kwargs["comment"] == "Tesla T4"


# --- add_pci_mapping_target ---


@pytest.mark.asyncio
async def test_add_pci_mapping_target_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import add_pci_mapping_target

    result = await add_pci_mapping_target(mapping_id="gpu0", node="pve2", path="01:00.0")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_add_pci_mapping_target_confirmed(mock_client):
    from proxmox_mcp.tools.pci import add_pci_mapping_target

    existing = {"id": "gpu0", "map": ["node=pve1,path=0000:01:00.0,id=10de:1eb8"]}
    mock_client.api_call = AsyncMock(side_effect=[existing, [SAMPLE_DEVICE], None])
    result = await add_pci_mapping_target(
        mapping_id="gpu0", node="pve2", path="01:00.0", confirm=True
    )

    assert result["status"] == "success"
    assert result["total_targets"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pci_tools.py -v -k "create_pci_mapping or add_pci_mapping_target"`
Expected: FAIL with `ImportError: cannot import name 'create_pci_mapping'`

- [ ] **Step 3: Implement the helpers and tools**

Add to `src/proxmox_mcp/tools/pci.py`, after the `list_pci_mappings` function:

```python
def _build_map_entry(node: str, path: str, device: dict) -> str:
    """Build a /cluster/mapping/pci map property-string from a device listing entry."""
    parts = [f"node={node}", f"path={path}"]
    vendor = device.get("vendor", "")
    dev_id = device.get("device", "")
    if vendor and dev_id:
        parts.append(f"id={vendor.removeprefix('0x')}:{dev_id.removeprefix('0x')}")
    iommu_group = device.get("iommugroup")
    if iommu_group is not None:
        parts.append(f"iommu-group={iommu_group}")
    subsystem_vendor = device.get("subsystem_vendor")
    subsystem_device = device.get("subsystem_device")
    if subsystem_vendor and subsystem_device:
        parts.append(
            f"subsystem-id={subsystem_vendor.removeprefix('0x')}:"
            f"{subsystem_device.removeprefix('0x')}"
        )
    return ",".join(parts)


async def _lookup_pci_device(client: "ProxmoxClient", node: str, path: str) -> dict:
    """Find a PCI device on `node` whose bus address matches `path`."""
    devices = await client.api_call(client.api.nodes(node).hardware.pci.get)
    normalized = path if path.count(":") == 2 else f"0000:{path}"
    for device in devices:
        dev_id = device.get("id", "")
        if dev_id == path or dev_id == normalized or dev_id.endswith(path):
            return device
    raise InvalidParameterError(
        f"No PCI device found at path '{path}' on node '{node}'. "
        f"Use list_node_pci_devices to see available devices."
    )


@mcp.tool()
async def create_pci_mapping(
    mapping_id: str,
    node: str,
    path: str,
    comment: str | None = None,
    confirm: bool = False,
) -> dict:
    """Create a cluster-wide PCI hardware mapping from one node's device.

    Set confirm=True to execute.

    Args:
        mapping_id: Name for the mapping (e.g. 'gpu0'). Used in
            assign_pci_device to attach this device to a VM.
        node: The node where the physical device currently lives.
        path: PCI bus address of the device (e.g. '01:00.0' or '0000:01:00.0').
            Use list_node_pci_devices to find it.
        comment: Optional description.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_pci_mapping_id(mapping_id)
        validate_node_name(node)
        client.validate_node(node)
        validate_pci_path(path)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will create PCI hardware mapping '{mapping_id}' "
                    f"pointing at '{path}' on node '{node}'."
                ),
                "action": "Call create_pci_mapping with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response(
                "create_pci_mapping", mapping_id=mapping_id, node=node, path=path
            )
        device = await _lookup_pci_device(client, node, path)
        map_entry = _build_map_entry(node, path, device)
        kwargs: dict = {"id": mapping_id, "map": [map_entry]}
        if comment:
            kwargs["comment"] = comment
        logger.info("Creating PCI mapping '%s' -> %s on node '%s'", mapping_id, path, node)
        await client.api_call(client.api.cluster.mapping.pci.post, **kwargs)
        return {
            "status": "success",
            "mapping_id": mapping_id,
            "node": node,
            "path": path,
            "map_entry": map_entry,
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def add_pci_mapping_target(
    mapping_id: str,
    node: str,
    path: str,
    confirm: bool = False,
) -> dict:
    """Add another node's matching device to an existing PCI mapping.

    This is what makes a mapping resolve correctly regardless of which node
    a VM lands on. Set confirm=True to execute.

    Args:
        mapping_id: Name of the existing mapping to extend.
        node: The additional node where a matching device lives.
        path: PCI bus address of the device on that node.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_pci_mapping_id(mapping_id)
        validate_node_name(node)
        client.validate_node(node)
        validate_pci_path(path)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will add node '{node}' path '{path}' as a target "
                    f"of PCI mapping '{mapping_id}'."
                ),
                "action": "Call add_pci_mapping_target with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response(
                "add_pci_mapping_target", mapping_id=mapping_id, node=node, path=path
            )
        existing = await client.api_call(client.api.cluster.mapping.pci(mapping_id).get)
        device = await _lookup_pci_device(client, node, path)
        map_entry = _build_map_entry(node, path, device)
        current_map = list(existing.get("map", []))
        current_map.append(map_entry)
        await client.api_call(client.api.cluster.mapping.pci(mapping_id).put, map=current_map)
        logger.info("Added node '%s' path '%s' to PCI mapping '%s'", node, path, mapping_id)
        return {
            "status": "success",
            "mapping_id": mapping_id,
            "node": node,
            "path": path,
            "map_entry": map_entry,
            "total_targets": len(current_map),
        }
    except Exception as e:
        return format_error_response(e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pci_tools.py -v -k "create_pci_mapping or add_pci_mapping_target"`
Expected: PASS, 9 tests

- [ ] **Step 5: Lint and type-check**

Run: `.venv/bin/ruff check src/proxmox_mcp/tools/pci.py tests/test_pci_tools.py && .venv/bin/mypy src/proxmox_mcp/tools/pci.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/proxmox_mcp/tools/pci.py tests/test_pci_tools.py
git commit -m "feat: add create_pci_mapping and add_pci_mapping_target"
```

---

## Task 4: `delete_pci_mapping`

**Files:**
- Modify: `src/proxmox_mcp/tools/pci.py`
- Test: `tests/test_pci_tools.py`

**Interfaces:**
- Consumes: `validate_pci_mapping_id` (Task 1), `client.api_call`, `client.dry_run_response`.
- Produces: `delete_pci_mapping(mapping_id: str, confirm: bool = False) -> dict`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pci_tools.py`:

```python
# --- delete_pci_mapping ---


@pytest.mark.asyncio
async def test_delete_pci_mapping_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    result = await delete_pci_mapping(mapping_id="gpu0")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_delete_pci_mapping_confirmed(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    mock_client.api_call = AsyncMock(return_value=None)
    result = await delete_pci_mapping(mapping_id="gpu0", confirm=True)

    assert result["status"] == "success"
    assert result["deleted"] is True


@pytest.mark.asyncio
async def test_delete_pci_mapping_dry_run(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await delete_pci_mapping(mapping_id="gpu0", confirm=True)
    assert result["status"] == "dry_run"


@pytest.mark.asyncio
async def test_delete_pci_mapping_invalid_id(mock_client):
    from proxmox_mcp.tools.pci import delete_pci_mapping

    result = await delete_pci_mapping(mapping_id="0bad", confirm=True)
    assert result["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pci_tools.py -v -k delete_pci_mapping`
Expected: FAIL with `ImportError: cannot import name 'delete_pci_mapping'`

- [ ] **Step 3: Implement the tool**

Add to `src/proxmox_mcp/tools/pci.py`, after `add_pci_mapping_target`:

```python
@mcp.tool()
async def delete_pci_mapping(mapping_id: str, confirm: bool = False) -> dict:
    """Delete a cluster-wide PCI hardware mapping. Set confirm=True to execute.

    Args:
        mapping_id: Name of the mapping to delete.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_pci_mapping_id(mapping_id)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete PCI hardware mapping '{mapping_id}'.",
                "action": "Call delete_pci_mapping with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_pci_mapping", mapping_id=mapping_id)
        logger.warning("Deleting PCI mapping '%s'", mapping_id)
        await client.api_call(client.api.cluster.mapping.pci(mapping_id).delete)
        return {"status": "success", "mapping_id": mapping_id, "deleted": True}
    except Exception as e:
        return format_error_response(e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pci_tools.py -v -k delete_pci_mapping`
Expected: PASS, 4 tests

- [ ] **Step 5: Lint and type-check**

Run: `.venv/bin/ruff check src/proxmox_mcp/tools/pci.py tests/test_pci_tools.py && .venv/bin/mypy src/proxmox_mcp/tools/pci.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/proxmox_mcp/tools/pci.py tests/test_pci_tools.py
git commit -m "feat: add delete_pci_mapping"
```

---

## Task 5: VM attachment (`assign_pci_device`, `remove_pci_device`)

**Files:**
- Modify: `src/proxmox_mcp/tools/pci.py`
- Test: `tests/test_pci_tools.py`

**Interfaces:**
- Consumes: `validate_vmid` (`utils/validators.py`), `validate_pci_slot`, `validate_pci_mapping_id` (Task 1), `client.check_protected`, `client.resolve_node`, `client.api_call`.
- Produces: `assign_pci_device(vmid: int, slot: int, mapping_id: str, node: str | None = None, pcie: bool = True, rombar: bool = True, x_vga: bool = False, confirm: bool = False) -> dict`, `remove_pci_device(vmid: int, slot: int, node: str | None = None, confirm: bool = False) -> dict`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pci_tools.py`:

```python
# --- assign_pci_device ---


@pytest.mark.asyncio
async def test_assign_pci_device_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device

    result = await assign_pci_device(vmid=100, slot=0, mapping_id="gpu0")
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_assign_pci_device_confirmed(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device

    mock_client.api_call = AsyncMock(return_value=None)
    result = await assign_pci_device(vmid=100, slot=0, mapping_id="gpu0", confirm=True)

    assert result["status"] == "success"
    assert result["vmid"] == 100
    assert result["node"] == "pve1"
    assert result["slot"] == 0
    assert "mapping=gpu0" in result["config_value"]
    assert "pcie=1" in result["config_value"]
    assert "rombar=1" in result["config_value"]
    assert "x-vga=0" in result["config_value"]


@pytest.mark.asyncio
async def test_assign_pci_device_protected(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await assign_pci_device(vmid=100, slot=0, mapping_id="gpu0", confirm=True)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_assign_pci_device_invalid_slot(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device

    result = await assign_pci_device(vmid=100, slot=99, mapping_id="gpu0", confirm=True)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_assign_pci_device_dry_run(mock_client):
    from proxmox_mcp.tools.pci import assign_pci_device

    mock_client.is_dry_run = True
    mock_client.dry_run_response.return_value = {"status": "dry_run"}
    result = await assign_pci_device(vmid=100, slot=0, mapping_id="gpu0", confirm=True)
    assert result["status"] == "dry_run"


# --- remove_pci_device ---


@pytest.mark.asyncio
async def test_remove_pci_device_requires_confirm(mock_client):
    from proxmox_mcp.tools.pci import remove_pci_device

    result = await remove_pci_device(vmid=100, slot=0)
    assert result["status"] == "confirmation_required"


@pytest.mark.asyncio
async def test_remove_pci_device_confirmed(mock_client):
    from proxmox_mcp.tools.pci import remove_pci_device

    mock_client.api_call = AsyncMock(return_value=None)
    result = await remove_pci_device(vmid=100, slot=0, confirm=True)

    assert result["status"] == "success"
    assert result["vmid"] == 100
    assert result["slot"] == 0
    call_kwargs = mock_client.api_call.call_args.kwargs
    assert call_kwargs["delete"] == "hostpci0"


@pytest.mark.asyncio
async def test_remove_pci_device_protected(mock_client):
    from proxmox_mcp.tools.pci import remove_pci_device
    from proxmox_mcp.utils.errors import ProtectedResourceError

    mock_client.check_protected.side_effect = ProtectedResourceError("protected")
    result = await remove_pci_device(vmid=100, slot=0, confirm=True)
    assert result["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pci_tools.py -v -k "assign_pci_device or remove_pci_device"`
Expected: FAIL with `ImportError: cannot import name 'assign_pci_device'`

- [ ] **Step 3: Implement the tools**

Add to `src/proxmox_mcp/tools/pci.py`, after `delete_pci_mapping`. This also requires `validate_vmid` to already be imported (it was added to the `from proxmox_mcp.utils.validators import validate_node_name, validate_vmid` line in Task 2's Step 3 — no further import change needed here):

```python
@mcp.tool()
async def assign_pci_device(
    vmid: int,
    slot: int,
    mapping_id: str,
    node: str | None = None,
    pcie: bool = True,
    rombar: bool = True,
    x_vga: bool = False,
    confirm: bool = False,
) -> dict:
    """Attach a PCI hardware mapping to a VM's hostpci slot. Set confirm=True to execute.

    Args:
        vmid: The VM ID.
        slot: hostpci slot number (0-15).
        mapping_id: Name of an existing PCI hardware mapping (see list_pci_mappings).
        node: The node name. Auto-detected if omitted.
        pcie: Present as a PCIe device (default True; required for most modern GPUs).
        rombar: Enable the device's ROM BAR (default True).
        x_vga: Mark as the VM's primary VGA device (default False).
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_pci_slot(slot)
        validate_pci_mapping_id(mapping_id)
        client.check_protected(vmid)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will attach PCI mapping '{mapping_id}' to VM {vmid} "
                    f"as hostpci{slot}."
                ),
                "action": "Call assign_pci_device with confirm=True to proceed.",
            }
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response(
                "assign_pci_device", vmid=vmid, slot=slot, mapping_id=mapping_id
            )
        value = (
            f"mapping={mapping_id},pcie={1 if pcie else 0},"
            f"rombar={1 if rombar else 0},x-vga={1 if x_vga else 0}"
        )
        kwargs = {f"hostpci{slot}": value}
        logger.info(
            "Assigning PCI mapping '%s' to VM %d as hostpci%d", mapping_id, vmid, slot
        )
        await client.api_call(client.api.nodes(node).qemu(vmid).config.put, **kwargs)
        return {
            "status": "success",
            "vmid": vmid,
            "node": node,
            "slot": slot,
            "mapping_id": mapping_id,
            "config_value": value,
        }
    except Exception as e:
        return format_error_response(e)


@mcp.tool()
async def remove_pci_device(
    vmid: int,
    slot: int,
    node: str | None = None,
    confirm: bool = False,
) -> dict:
    """Detach a PCI device from a VM's hostpci slot. Set confirm=True to execute.

    Args:
        vmid: The VM ID.
        slot: hostpci slot number (0-15) to clear.
        node: The node name. Auto-detected if omitted.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        validate_vmid(vmid)
        validate_pci_slot(slot)
        client.check_protected(vmid)
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will remove hostpci{slot} from VM {vmid}.",
                "action": "Call remove_pci_device with confirm=True to proceed.",
            }
        node = await client.resolve_node(vmid, node)
        if client.is_dry_run:
            return client.dry_run_response("remove_pci_device", vmid=vmid, slot=slot)
        logger.warning("Removing hostpci%d from VM %d", slot, vmid)
        await client.api_call(
            client.api.nodes(node).qemu(vmid).config.put, delete=f"hostpci{slot}"
        )
        return {"status": "success", "vmid": vmid, "node": node, "slot": slot}
    except Exception as e:
        return format_error_response(e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pci_tools.py -v -k "assign_pci_device or remove_pci_device"`
Expected: PASS, 9 tests

- [ ] **Step 5: Lint and type-check**

Run: `.venv/bin/ruff check src/proxmox_mcp/tools/pci.py tests/test_pci_tools.py && .venv/bin/mypy src/proxmox_mcp/tools/pci.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/proxmox_mcp/tools/pci.py tests/test_pci_tools.py
git commit -m "feat: add assign_pci_device and remove_pci_device"
```

---

## Task 6: Register module, update docs, full-suite verification

**Files:**
- Modify: `src/proxmox_mcp/server.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `src/proxmox_mcp/tools/pci.py` (Tasks 2-5) — the module must be importable with no errors for registration to succeed.
- Produces: nothing new — this task wires the finished module into the running server and keeps docs in sync.

- [ ] **Step 1: Register `pci` in `server.py`**

In `src/proxmox_mcp/server.py`, the tool-module import block currently reads:

```python
from proxmox_mcp.tools import (  # noqa: E402, F401
    backup,
    cluster,
    container,
    disk,
    network,
    node,
    ssh_tools,
    storage,
    task,
    vm,
)
```

Change it to:

```python
from proxmox_mcp.tools import (  # noqa: E402, F401
    backup,
    cluster,
    container,
    disk,
    network,
    node,
    pci,
    ssh_tools,
    storage,
    task,
    vm,
)
```

- [ ] **Step 2: Verify the server imports cleanly**

Run: `.venv/bin/python -c "import proxmox_mcp.server"`
Expected: no output, exit code 0 (requires a `.env` with at least `PROXMOX_HOST` set, or run inside the test environment where `conftest.py` mocks it — if this fails locally due to missing `.env`, instead run the full test suite in Step 4 below, which exercises the same import path through `conftest.py`'s mocked `proxmox_mcp.server`).

- [ ] **Step 3: Update `README.md`**

In `README.md`, change line 3:

```
MCP (Model Context Protocol) server for managing Proxmox VE infrastructure through AI assistants like Claude. Exposes **91 tools**, **10 resources**, and **6 prompt templates** via FastMCP.
```

to:

```
MCP (Model Context Protocol) server for managing Proxmox VE infrastructure through AI assistants like Claude. Exposes **98 tools**, **10 resources**, and **6 prompt templates** via FastMCP.
```

Change line 7:

```
- **91 tools** across 9 domains: VMs, containers, storage, networking, backups, cluster, nodes, tasks, and disk management
```

to:

```
- **98 tools** across 10 domains: VMs, containers, storage, networking, PCI passthrough, backups, cluster, nodes, tasks, and disk management
```

After the "### Disk Management (5 tools, SSH-based)" table (ends around line 208-209, right before `## Configuration Reference`), insert:

```markdown
### PCI Passthrough (7 tools)

| Tool | Description |
|------|-------------|
| `list_node_pci_devices` | List PCI devices on a node (with IOMMU group) |
| `list_pci_mappings` | List cluster-wide PCI hardware mappings |
| `create_pci_mapping` | Create a PCI hardware mapping from a node's device |
| `add_pci_mapping_target` | Add another node's device to an existing mapping |
| `delete_pci_mapping` | Delete a PCI hardware mapping |
| `assign_pci_device` | Attach a PCI mapping to a VM's hostpci slot |
| `remove_pci_device` | Detach a PCI device from a VM's hostpci slot |
```

- [ ] **Step 4: Run the full verification suite**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/mypy src/proxmox_mcp && .venv/bin/python -m pytest tests/ -q`
Expected: ruff clean, mypy shows only the same pre-existing findings as before this feature (no new `no-any-return` — `pci.py` follows the typed `get_client()`/`get_mcp()` pattern from the start), full test suite passes with the new PCI tests included (346 existing + ~26 new PCI tests + 14 validator tests ≈ 386 passed, 3 skipped — exact count depends on final test enumeration, verify it's strictly greater than 346 and nothing failed).

- [ ] **Step 5: Commit**

```bash
git add src/proxmox_mcp/server.py README.md
git commit -m "feat: register PCI passthrough tools and update docs"
```

---

## Self-Review Notes

- **Spec coverage:** All 7 tools from the design doc are covered (Tasks 2-5). All 3 validators covered (Task 1). Registration + README covered (Task 6). "Not building" items from the design (raw-ID mode, mdev/vGPU, USB, a redundant "list VM's PCI devices" tool, IOMMU enforcement logic) are correctly absent from every task.
- **Placeholder scan:** No TBD/TODO; every step has complete, runnable code.
- **Type consistency:** `mapping_id`/`node`/`path`/`slot`/`vmid`/`confirm` parameter names and types are identical across the design doc, every task's code, and every task's tests. `_build_map_entry`/`_lookup_pci_device` signatures introduced in Task 3 are not referenced by name in Tasks 4-5 (they don't need them) — consistent.
