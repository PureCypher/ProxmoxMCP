FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/proxmox-mcp /usr/local/bin/proxmox-mcp
COPY src/ src/

ENV MCP_TRANSPORT=streamable-http
ENV MCP_HTTP_PORT=3001

EXPOSE 3001

CMD ["proxmox-mcp"]
