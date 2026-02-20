from proxmox_mcp.utils.errors import (
    ProxmoxMCPError,
    ProxmoxConnectionError,
    AuthenticationError,
    VMNotFoundError,
    ContainerNotFoundError,
    NodeNotFoundError,
    ProtectedResourceError,
    NodeNotAllowedError,
    TaskTimeoutError,
    InsufficientPermissionsError,
    InvalidParameterError,
    format_error_response,
)


def test_all_exceptions_inherit_from_base():
    for exc_class in [
        ProxmoxConnectionError, AuthenticationError, VMNotFoundError,
        ContainerNotFoundError, NodeNotFoundError, ProtectedResourceError,
        NodeNotAllowedError, TaskTimeoutError, InsufficientPermissionsError,
        InvalidParameterError,
    ]:
        assert issubclass(exc_class, ProxmoxMCPError)


def test_format_error_response():
    result = format_error_response(
        VMNotFoundError("VM 999 not found"),
        suggestion="Use list_vms to see available VMs.",
    )
    assert result["status"] == "error"
    assert result["error_type"] == "VMNotFoundError"
    assert "999" in result["message"]
    assert result["suggestion"] == "Use list_vms to see available VMs."


def test_format_error_response_no_suggestion():
    result = format_error_response(ProxmoxConnectionError("timeout"))
    assert result["status"] == "error"
    assert "suggestion" not in result
