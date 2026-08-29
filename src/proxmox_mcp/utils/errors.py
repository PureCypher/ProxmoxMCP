"""Custom exception hierarchy for Proxmox MCP server."""


class ProxmoxMCPError(Exception):
    """Base exception for all Proxmox MCP errors."""


class ProxmoxConnectionError(ProxmoxMCPError):
    """Failed to connect to Proxmox host."""

    default_suggestion = (
        "Check PROXMOX_HOST/PROXMOX_PORT and that the node is reachable "
        "(network, firewall, service)."
    )


class AuthenticationError(ProxmoxMCPError):
    """Authentication with Proxmox failed."""

    default_suggestion = "Check PROXMOX_TOKEN_NAME/VALUE or PROXMOX_USER/PASSWORD."


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


class SSHExecutionError(ProxmoxMCPError):
    """SSH command execution failed."""


class SafetyGateError(ProxmoxMCPError):
    """A safety gate check prevented the operation."""


class DeviceNotFoundError(ProxmoxMCPError):
    """Block device not found on the node."""


class DeviceInUseError(ProxmoxMCPError):
    """Block device or partition is currently in use."""


def format_error_response(error: Exception, suggestion: str | None = None) -> dict:
    """Format any exception into a structured error response dict.

    Falls back to the exception class's `default_suggestion` (when defined)
    if no explicit suggestion is given.
    """
    result = {
        "status": "error",
        "error_type": type(error).__name__,
        "message": str(error),
    }
    if suggestion is None:
        suggestion = getattr(type(error), "default_suggestion", None)
    if suggestion:
        result["suggestion"] = suggestion
    return result
