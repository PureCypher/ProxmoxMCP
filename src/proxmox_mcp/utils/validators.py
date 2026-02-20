"""Input validation helpers."""

import re
from proxmox_mcp.utils.errors import InvalidParameterError


def validate_vmid(vmid: int) -> None:
    """Validate VMID is in the acceptable range (100+)."""
    if vmid < 100:
        raise InvalidParameterError(f"VMID {vmid} is invalid. VMIDs must be >= 100.")


def validate_node_name(node: str) -> None:
    """Validate node name format."""
    if not node or not node.strip():
        raise InvalidParameterError("Node name cannot be empty.")
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*$", node):
        raise InvalidParameterError(
            f"Node name '{node}' is invalid. Must be alphanumeric with optional hyphens."
        )
