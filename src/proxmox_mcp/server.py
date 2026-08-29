"""FastMCP server definition and entry point for Proxmox VE Manager."""

import logging
import secrets

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.ssh import SSHExecutor

# Initialize config and logging
config = ProxmoxConfig()
logging.basicConfig(
    level=getattr(logging, str(config.LOG_LEVEL).upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("proxmox-mcp")

# Create MCP server
mcp = FastMCP(
    "Proxmox VE Manager",
    json_response=True,
    port=config.MCP_HTTP_PORT,
    instructions=(
        "You are connected to a Proxmox Virtual Environment cluster. "
        "Use the available tools to manage VMs, containers, nodes, storage, and backups. "
        "Always check the current state before making changes. "
        "For destructive operations (delete, stop, rollback), confirm with the user first. "
        "Protected VMIDs cannot be modified or deleted."
    ),
)

# Lazily-initialized singletons. The module-level __getattr__ (PEP 562) keeps
# the historical `proxmox_client` / `ssh_executor` attributes working so
# `from proxmox_mcp.server import proxmox_client` continues to work everywhere.
_client: ProxmoxClient | None = None
_executor: SSHExecutor | None = None


def get_server_client() -> ProxmoxClient:
    """Return the shared Proxmox client, constructing it on first use."""
    global _client
    if _client is None:
        _client = ProxmoxClient(config)
    return _client


def get_ssh_executor() -> SSHExecutor:
    """Return the shared SSH executor, constructing it on first use."""
    global _executor
    if _executor is None:
        _executor = SSHExecutor(config)
    return _executor


def __getattr__(name: str):
    """PEP 562 lazy module attributes: proxmox_client / ssh_executor."""
    if name == "proxmox_client":
        return get_server_client()
    if name == "ssh_executor":
        return get_ssh_executor()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer <MCP_HTTP_AUTH_TOKEN>` on every request."""

    def __init__(self, app, expected_token: str) -> None:
        super().__init__(app)
        self._expected_token = expected_token.encode("utf-8")

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(
            token.encode("utf-8"), self._expected_token
        ):
            return JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


def _run_http() -> None:
    """Start the streamable-http transport. A bearer token is mandatory."""
    if not config.MCP_HTTP_AUTH_TOKEN:
        raise RuntimeError(
            "MCP_TRANSPORT='streamable-http' requires MCP_HTTP_AUTH_TOKEN: the HTTP "
            "endpoint would otherwise be reachable without any authentication. "
            "Set MCP_HTTP_AUTH_TOKEN to a strong secret value, or use "
            "MCP_TRANSPORT='stdio' for local stdio connections."
        )
    app = mcp.streamable_http_app()
    app.add_middleware(BearerTokenAuthMiddleware, expected_token=config.MCP_HTTP_AUTH_TOKEN)
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=config.MCP_HTTP_PORT,
        log_level=str(config.LOG_LEVEL).lower(),
    )


def main():
    """Entry point for the MCP server."""
    # Import prompt/resource/tool modules so they self-register on `mcp`.
    # (Deferred to startup so the real client is not constructed at import time.)
    import proxmox_mcp.prompts.prompts
    import proxmox_mcp.resources.resources
    import proxmox_mcp.tools.backup
    import proxmox_mcp.tools.cluster
    import proxmox_mcp.tools.container
    import proxmox_mcp.tools.disk
    import proxmox_mcp.tools.network
    import proxmox_mcp.tools.node
    import proxmox_mcp.tools.pci
    import proxmox_mcp.tools.ssh_tools
    import proxmox_mcp.tools.storage
    import proxmox_mcp.tools.task
    import proxmox_mcp.tools.vm  # noqa: F401

    if not config.PROXMOX_VERIFY_SSL:
        logger.warning(
            "PROXMOX_VERIFY_SSL=false — API TLS verification DISABLED; vulnerable to MITM"
        )
    logger.info("Starting Proxmox VE MCP Server")
    if config.MCP_TRANSPORT == "streamable-http":
        _run_http()
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
