"""FastMCP server definition and entry point for Proxmox VE Manager."""

import logging

from mcp.server.fastmcp import FastMCP

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.config import ProxmoxConfig
from proxmox_mcp.ssh import SSHExecutor

# Initialize config and logging
config = ProxmoxConfig()
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("proxmox-mcp")

# Create MCP server
mcp = FastMCP(
    "Proxmox VE Manager",
    json_response=True,
    instructions=(
        "You are connected to a Proxmox Virtual Environment cluster. "
        "Use the available tools to manage VMs, containers, nodes, storage, and backups. "
        "Always check the current state before making changes. "
        "For destructive operations (delete, stop, rollback), confirm with the user first. "
        "Protected VMIDs cannot be modified or deleted."
    ),
)

# Initialize Proxmox client and SSH executor
proxmox_client = ProxmoxClient(config)
ssh_executor = SSHExecutor(config)

# Import tool modules to register them with mcp
from proxmox_mcp.prompts import prompts  # noqa: E402, F401
from proxmox_mcp.resources import resources  # noqa: E402, F401
from proxmox_mcp.tools import (  # noqa: E402, F401  # noqa: E402, F401  # noqa: E402, F401
    backup,
    cluster,
    container,
    disk,
    network,
    node,
    storage,
    task,
    vm,
)


def main():
    """Entry point for the MCP server."""
    logger.info("Starting Proxmox VE MCP Server")
    if config.MCP_TRANSPORT == "streamable-http":
        mcp.run(transport="streamable-http", port=config.MCP_HTTP_PORT)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
