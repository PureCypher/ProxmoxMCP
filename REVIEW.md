# ProxmoxMCP — Full-Spectrum Code Review

Date: 2026-08-29 · Branch: main · Method: 7 specialist agents (security, architecture, performance, protocol, testing, packaging, docs), orchestrator-verified P0/P1.

Repo is a flat fork (no `core/`/`formatting/` subpackages, no `get_nodes`; it is `list_nodes`; guest command exec is SSH-based via `ssh_tools.py`, not QEMU guest-agent).

## Executive summary (post-dedup, all P0/P1 orchestrator-verified)

| Severity | Count |
|----------|-------|
| P0 | 2 |
| P1 | 18 |
| P2 | ~30 |
| P3 | ~35 |

Baseline (pre-fix): 397 passed / 3 skipped, 0 failed · ruff check clean · ruff format: 22 files dirty · black --check: 15 files dirty · mypy: 13 errors in 8 files · bandit: 5 low/medium (ssh B507, B601, 2× B110, B108) · pip-audit: all locked versions current (requests 2.32.5, urllib3 2.6.3, cryptography 46.0.5, paramiko 4.0.0, httpx 0.28.1, pyjwt 2.11.0, mcp 1.26.0, anyio 4.12.1).

## Security (P0/P1)

- **[P0] src/proxmox_mcp/server.py:58 / Dockerfile:19-22 — `streamable-http` transport has no authentication; the Docker image runs it on :3001 unauthenticated, exposing full Proxmox admin + RCE to any network peer → make auth mandatory: config `MCP_HTTP_AUTH_TOKEN`; server passes `auth_server_settings` to FastMCP and refuses to start over HTTP without one; Dockerfile sets a required env var.**
- **[P0] Dockerfile:8 — builder uses `pip install .`, bypassing uv.lock entirely (non-reproducible, un-audited versions) → `COPY pyproject.toml uv.lock; RUN uv sync --frozen` (or pip-compile from a generated requirements pinning the lock), copy the venv.**
- **[P1] src/proxmox_mcp/tools/ssh_tools.py:554 (`target_ip`) — only metacharacters are rejected; an LLM/client can point root SSH + `execute_script` at 169.254.169.254 or the LAN gateway → strict IPv4/IPv6 literal check (+ optional hostname allowlist via new config), reject otherwise. `execute_script` is arbitrary remote code execution with no confirm gate and a bland docstring → add `confirm=True` (backward-compatible default False returns a `confirmation_required` response, matching every other destructive tool) and an "EXECUTES ARBITRARY COMMANDS" warning in the docstring.
- **[P1] src/proxmox_mcp/tools/ssh_tools.py — none of the 5 SSH tools honors `PROXMOX_DRY_RUN` (verified: 0 `is_dry_run` hits) → add dry-run gate to all 5, returning `client.dry_run_response(...)`.
- **[P1] src/proxmox_mcp/ssh.py:150 — `execute()` ignores its `node` argument and always connects to `PROXMOX_HOST`; in multi-node clusters every disk tool silently hits the API host → connect to the node name, falling back to PROXMOX_HOST only when the node doesn't resolve (keep single-node behavior).
- **[P1] src/proxmox_mcp/config.py:13 — `PROXMOX_VERIFY_SSL=False` default with no runtime warning (silent MITM) → log a prominent one-time WARNING at server startup when false.
- **[P1] src/proxmox_mcp/tools/ssh_tools.py:206-225 — `_detect_package_manager` opens up to 6 sequential SSH connections (worst case ~60s) per call → one combined `command -v a b c …` probe over one connection.
- **[P1] src/proxmox_mcp/tools/container.py:113 — `start_container` never calls `client.check_protected(vmid)` (verified; all 5 sibling mutators do) → add the guard.

## Correctness (P1)

- **[P1] src/proxmox_mcp/client.py:76-81 — `api_call` classifies errors by substring on `str(e)` ("401"/"authentication"/"connection"); a 403 or a body containing "connection" is misclassified, and raw proxmoxer exception text (may echo hostnames) leaks to MCP clients → branch on `proxmoxer.ProxmoxAPIError.status_code` (401→AuthenticationError, 403→InsufficientPermissionsError, else→ProxmoxConnectionError/ProxmoxMCPError), keep string match only as fallback.
- **[P1] src/proxmox_mcp/tools/vm.py:156-170 — `start_vm`'s `timeout` param is advertised but dead (never passed) → wire `timeout=` into the API call (or remove param; wiring is non-breaking).
- **[P1] src/proxmox_mcp/tools/vm.py:625,627,631,635 — mypy-confirmed str→int reassignment bug in `modify_vm_config` (memory/cores/sockets/balloon) → fix the assignments + add regression test.
- **[P1] src/proxmox_mcp/tools/backup.py:363 — docstring claims `schedule` is cron ("0 2 * * *"); PVE expects `hourly|daily|weekly|monthly|at HH:mm` → fix docstring + add `validate_schedule`.
- **[P1] src/proxmox_mcp/tools/vm.py:129 / cluster.py:112 / task.py:153,174 — unclamped inputs: `timeframe` unvalidated (raw API error on typos), `max_entries` unbounded, `wait_for_task(timeout)` unbounded, `poll_interval=0` tight infinite loop → validate timeframe enum, clamp max_entries ≤1000, timeout ≤3600, poll_interval ≥1.
- **[P1] src/proxmox_mcp/tools/node.py:184 / vm.py:186 — `get_node_syslog(since)` docstring claims 'YYYY-MM-DD' but the PVE syslog API takes a unix epoch; `shutdown_vm`/`shutdown_container` `timeout` kwarg is a dead query param → correct docstrings; drop dead kwarg.
- **[P1] src/proxmox_mcp/tools/ssh_tools.py:499 & :589 — `transfer_file`/`execute_script` inline the whole base64 payload in one shell command (ARG_MAX blowout on large content) → chunk the write.
- **[P1] src/proxmox_mcp/tools/ssh_tools.py:503 (`owner`) — `chown {owner}` with dash-prefixed values allows shell-option injection → require `^[\w.-]+(:[\w.-]+)?$`.
- **[P1] src/proxmox_mcp/tools/ssh_tools.py:84,95 — bare `except Exception: pass` in `_resolve_vm_ip` hides 401/offline as "Cannot discover IP" → log at DEBUG, only fall through for 404.
- **[P1] src/proxmox_mcp/ssh_tools.py:557 — `ssh_port` unvalidated (0/negative/>65535 reach paramiko) → 1–65535 check.
- **[P1] src/proxmox_mcp/ssh.py:200 — full commands (incl. base64 script payloads) logged at INFO → DEBUG + truncate at INFO.

## Performance / async (P1 + key P2)

- **[P1] src/proxmox_mcp/ssh.py:117 — new paramiko TCP+TLS+auth connection per command (no reuse); multi-step disk flows do 7-8 sequential → per-host client cache with a bounded pool (or at least merge multi-step disk commands).
- **[P2] src/proxmox_mcp/tools/task.py:174-190 — `elapsed += poll_interval` drifts from wall clock (300s can become 600s+) and `poll_interval=0` spins → wall-clock deadline.
- **[P2] src/proxmox_mcp/client.py:83 — `resolve_node_for_vmid` does a full `cluster.resources.get(type="vm")` per call (N+1) → short-TTL cache.
- **[P2] src/proxmox_mcp/tools/vm.py:625 et al. — ~10 untyped `kwargs: dict` (mypy --strict blockers); 3 dead exception classes (`ContainerNotFoundError`, `NodeNotFoundError`, `InsufficientPermissionsError` in utils/errors.py, 0 usages).
- **[P2] src/proxmox_mcp/tools/ssh_tools.py — 8-param SSH override block + identical response dict repeated in all 5 tools → shared helper.
- **[P2] src/proxmox_mcp/tools/vm.py:641 et al. (~15 sites) — `format_error_response(Exception("…"))` defeats the exception hierarchy → `raise InvalidParameterError`.
- **[P2] src/proxmox_mcp/config.py:42-56 — config validates almost nothing (no auth-pair check, `LOG_LEVEL` typo → silent default, `PROXMOX_PROTECTED_VMIDS="abc"` → raw `ValueError`; verified empirically) → startup `model_validator`: one auth pair required, LOG_LEVEL enum, friendly vmid-parse error, port ranges; `transport: Literal["stdio","streamable-http"]`.
- **[P2] src/proxmox_mcp/server.py:34 — `ProxmoxClient(config)`/`SSHExecutor(config)` built at import time (crashes bare `uv run pytest`, breaks fresh-clone DX; see P0-below) → lazy accessor.
- **[P2] src/proxmox_mcp/tools/network.py:66,92 & ssh_tools `_resolve_vm_ip` — QEMU→LXC fallback swallows real 403/500 → distinguish 404 from other HTTP errors.
- **[P2] src/proxmox_mcp/tools/disk.py:105-120 — `grep -E '{device}'` can misfire on prefix matches (nvme0n1 vs nvme0n10) → anchor the pattern.
- **[P2] src/proxmox_mcp/tools/cluster.py:390 — `set_user_permission` can grant PVEAdmin on any path, no confirm, no role validation → validate roles + `confirm=True`.
- **[P2] src/proxmox_mcp/tools/container.py:284 — `rootfs_size` str is f-stringed into a volume spec ("8G" breaks) → int.
- **[P2] src/proxmox_mcp/tools/vm.py:84 — unknown `status_filter` silently returns empty list → validate enum.
- **[P2] src/proxmox_mcp/tools/vm.py:394,608; container.py:406 — opaque `ostype` and undocumented `extra_config` allowlists in docstrings → enumerate allowed values.
- **[P2] src/proxmox_mcp/tools/storage.py:429 — `download_to_storage(url)` has no scheme/host restriction (node-side SSRF) → http/https + optional allowed-host prefix.

## Protocol (P2/P3)

- Destructive-but-ungated tools inconsistent with the confirm pattern: stop_vm, reboot_vm, reset_vm, stop_container, reboot_container, create_user, wait_for_task → `confirm=True` where hard/destructive (optional param, non-breaking).
- `wait_for_task` docstring "raises a timeout error" but returns an error dict → correct docstring.
- `set_vm_cloudinit.sshkeys` docstring says "URL-encoded" — it is plain PEM → correct.
- `partition_disk` uses `confirm_destructive` vs universal `confirm` → keep param name (breaking to rename) but document the pattern.
- prompts.py:44,92 have no docstrings (schema descriptions missing); resources.py error shape `{"error": …}` diverges from tools' `format_error_response` → unify.
- `vm_deployment`/`troubleshoot_vm` args need descriptions; `create_backup_job.vmid` is comma-str while every other tool takes int → document.
- `download_to_storage`, `format_disk.options` (allowed flags unlisted), `partition_disk.label` ("hyphens/underscores" allowed by validator, docstring says otherwise), `get_node_syslog.since`, README "confirm=True" overclaim — all P3 docstring fixes.

## Testing / DX (P1 + key P2)

- **[P0-equivalent DX] fresh `uv run pytest` (no `--extra dev`) dies with 11 collection errors; a bare-clone `pytest tests/` crashes at collection with `pydantic_core.ValidationError: PROXMOX_HOST Field required` (reproduced with `env -i`) → conftest sets dummy `PROXMOX_*` env defaults at session start (docs also corrected).
- **[P1] tests/ — error-path coverage holes (verified by suite + file read): zero error-path tests in test_backup_tools.py, test_container_tools.py (6 of 13 tools untested); no SSHExecutionError path in test_ssh_tools.py; no 401/unreachable-host path in test_client.py; no API error path in test_vm_tools.py (5 lifecycle tools untested) → add these.
- **[P2] no dry-run test for SSH tools (no gate exists today — covered above); bad `PROXMOX_PROTECTED_VMIDS` untested; ~80 redundant `@pytest.mark.asyncio` markers → 170 warnings.
- Top-5 missing tests (testing agent, adopted): VM-not-found error dict · SSH connection failure at tool layer · paramiko socket.timeout → SSHExecutionError · bad PROXMOX_PROTECTED_VMIDS ValidationError · dry-run on ssh tools.

## Packaging (P1 + key P2)

- **[P1] no LICENSE file and no `license` field in pyproject → ship MIT (or chosen SPDX) + declare it.
- **[P1] Dockerfile — no USER (root on :3001), floating `python:3.12-slim`, COPY src before deps (cache buster), no HEALTHCHECK → non-root user, pin image, layer fix, healthcheck.
- **[P2] .coverage (binary, embeds absolute local paths) and docs/.DS_Store are git-tracked → `git rm --cached`, gitignore.
- **[P2] dev tools in `[project.optional-dependencies]` instead of `[dependency-groups]` (CI relies on `uv sync --dev`); no `uv lock --check` / audit step in CI → move to dependency-groups, add `uv lock --check`.
- mcp 1.26.0 vs 2.x current major, paramiko 4.0.0 vs 5.x — no CVEs; track in backlog.

## Docs (P1 + P2)

- **[P1] README.md:3 — "98 tools" is stale; real count is 103 (grep -c @mcp.tool()), and all 5 SSH guest tools are missing from the inventory.
- **[P1] README.md:261 / CLAUDE.md:7 — contributor command crashes on bare clone (see DX item); CLAUDE.md says "91 tools, 10 resources, 6 prompts"; README says 9 tool modules (actually 11, missing pci + ssh_tools).
- **[P2] README Configuration Reference omits PROXMOX_SSH_PASSWORD and PROXMOX_SSH_KNOWN_HOSTS → add both rows.
- README primary install is `pip install -e .` although the repo is uv-managed; no streamable-http example.

## Fix plan (Phase 3, disjoint file ownership)

| Agent | Owns (exclusive) |
|-------|------------------|
| A — ssh-hardening | src/proxmox_mcp/ssh.py, src/proxmox_mcp/tools/ssh_tools.py, src/proxmox_mcp/tools/disk.py, src/proxmox_mcp/utils/sanitizers.py; NEW tests/test_ssh_harden.py (may append to existing tests/test_ssh.py, tests/test_ssh_tools.py, tests/test_disk_tools.py) |
| B — core | src/proxmox_mcp/client.py, src/proxmox_mcp/config.py, src/proxmox_mcp/server.py, src/proxmox_mcp/tools/task.py, src/proxmox_mcp/tools/node.py, src/proxmox_mcp/utils/errors.py, src/proxmox_mcp/prompts/prompts.py, src/proxmox_mcp/resources/resources.py, src/proxmox_mcp/__main__.py; NEW tests/test_config_strict.py (may append to tests/test_config.py, tests/test_errors.py, tests/test_client.py, tests/test_task_tools.py, tests/test_node_tools.py, tests/test_prompts.py, tests/test_integration.py, and tests/conftest.py ONLY for the env-defaults DX fix) |
| C — tools | src/proxmox_mcp/tools/vm.py, container.py, cluster.py, network.py, pci.py, storage.py, backup.py; NEW tests/test_error_paths.py + appends to tests/test_vm_tools.py, test_container_tools.py, test_cluster_tools.py, test_network_tools.py, test_storage_tools.py, test_backup_tools.py |
| D — packaging/docs | Dockerfile, .dockerignore, .github/workflows/ci.yml, pyproject.toml, .gitignore, .env.example, README.md, CLAUDE.md, LICENSE (new); git-rm .coverage + docs/.DS_Store (metadata only, no content edits) |

Shared invariants for all agents:
- Never rename/remove MCP tools or change existing parameter names/defaults (adding optional params is OK; confirm-gates default to a `confirmation_required` response, not an exception).
- Every P0/P1 fix ships with a regression test in tests/.
- Atomic conventional commits, one per fix. No secrets/hostnames/token values. No new dependencies without a commit-body justification.
- After all agents: orchestrator runs the Phase 4 gauntlet (pytest, ruff check, ruff format --check, black --check, mypy, bandit, pip-audit, smoke test) and routes any regression back to the owning partition.
