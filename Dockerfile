# Pinned 3.12.x-slim tags + lockfile-respecting install (uv.lock, --frozen)
# for reproducible, auditable builds.
FROM python:3.12.13-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv

# Copy only the manifest + lockfile and install locked deps BEFORE the source
# so this layer stays cached across code-only changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
# Editable install of the project itself (deps already come from uv.lock)
RUN uv pip install -e . --no-deps

FROM python:3.12.13-slim

WORKDIR /app

# Copy the venv (locked deps + entry point) first, then the source,
# so the heavy dependency layer is cached.
COPY --from=builder /app/.venv /app/.venv
COPY src/ src/

RUN useradd -r mcp && chown -R mcp:mcp /app
USER mcp

ENV MCP_TRANSPORT=streamable-http
ENV MCP_HTTP_PORT=3001
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD /app/.venv/bin/python -c "import mcp, requests, paramiko"

CMD ["proxmox-mcp"]
