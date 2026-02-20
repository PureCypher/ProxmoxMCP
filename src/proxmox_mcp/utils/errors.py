"""Custom exception hierarchy for Proxmox MCP server."""


class ProxmoxMCPError(Exception):
    """Base exception for all Proxmox MCP errors."""


class ProxmoxConnectionError(ProxmoxMCPError):
    """Failed to connect to Proxmox host."""


class AuthenticationError(ProxmoxMCPError):
    """Authentication with Proxmox failed."""


class VMNotFoundError(ProxmoxMCPError):
    """QEMU VM not found in the cluster."""


class ContainerNotFoundError(ProxmoxMCPError):
    """LXC container not found in the cluster."""


class NodeNotFoundError(ProxmoxMCPError):
    """Proxmox node not found."""


class ProtectedResourceError(ProxmoxMCPError):
    """Operation blocked on a protected VMID."""


class NodeNotAllowedError(ProxmoxMCPError):
    """Node is not in the allowed nodes list."""


class TaskTimeoutError(ProxmoxMCPError):
    """A Proxmox task exceeded the timeout."""


class InsufficientPermissionsError(ProxmoxMCPError):
    """Insufficient Proxmox permissions for this operation."""


class InvalidParameterError(ProxmoxMCPError):
    """Invalid parameter value provided."""


def format_error_response(error: Exception, suggestion: str | None = None) -> dict:
    """Format any exception into a structured error response dict."""
    result = {
        "status": "error",
        "error_type": type(error).__name__,
        "message": str(error),
    }
    if suggestion:
        result["suggestion"] = suggestion
    return result
