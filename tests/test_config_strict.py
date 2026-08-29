"""Regression tests for the strict config validator and server startup checks."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError


def _cfg(env: dict, monkeypatch, extra: dict | None = None):
    """Build a ProxmoxConfig with a required auth pair plus the given env."""
    from proxmox_mcp.config import ProxmoxConfig

    defaults = {"PROXMOX_HOST": "h", "PROXMOX_TOKEN_NAME": "root@pam!t", "PROXMOX_TOKEN_VALUE": "v"}
    defaults.update(env)
    for key, value in defaults.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, str(value))
    for key, value in (extra or {}).items():
        monkeypatch.setenv(key, str(value))
    return ProxmoxConfig()


def test_bad_vmid_list_fails_with_friendly_message(monkeypatch):
    with pytest.raises(ValidationError, match="invalid VMID 'abc' in PROXMOX_PROTECTED_VMIDS"):
        _cfg({"PROXMOX_PROTECTED_VMIDS": "abc"}, monkeypatch)


def test_no_auth_pair_fails_with_actionable_message(monkeypatch):
    with pytest.raises(ValidationError, match="PROXMOX_TOKEN_NAME"):
        _cfg(
            {
                "PROXMOX_TOKEN_NAME": None,
                "PROXMOX_TOKEN_VALUE": None,
                "PROXMOX_USER": None,
                "PROXMOX_PASSWORD": None,
            },
            monkeypatch,
        )


def test_partial_auth_pair_is_insufficient(monkeypatch):
    with pytest.raises(ValidationError, match="auth pair"):
        _cfg({"PROXMOX_TOKEN_VALUE": None}, monkeypatch)


def test_password_pair_is_accepted(monkeypatch):
    config = _cfg(
        {
            "PROXMOX_TOKEN_NAME": None,
            "PROXMOX_TOKEN_VALUE": None,
            "PROXMOX_USER": "root",
            "PROXMOX_PASSWORD": "pw",
        },
        monkeypatch,
    )
    assert config.PROXMOX_USER == "root"


def test_bad_log_level_fails(monkeypatch):
    with pytest.raises(ValidationError, match="LOG_LEVEL 'verbose' is not a valid logging level"):
        _cfg({"LOG_LEVEL": "verbose"}, monkeypatch)


def test_bad_proxmox_port_fails(monkeypatch):
    with pytest.raises(ValidationError, match="PROXMOX_PORT"):
        _cfg({"PROXMOX_PORT": "99999"}, monkeypatch)


def test_bad_http_port_fails(monkeypatch):
    with pytest.raises(ValidationError, match="MCP_HTTP_PORT"):
        _cfg({"MCP_HTTP_PORT": "0"}, monkeypatch)


def test_unknown_transport_fails(monkeypatch):
    with pytest.raises(ValidationError, match="MCP_TRANSPORT"):
        _cfg({"MCP_TRANSPORT": "sse"}, monkeypatch)


def test_valid_transport_and_token_fields(monkeypatch):
    config = _cfg(
        {"MCP_TRANSPORT": "streamable-http", "MCP_HTTP_AUTH_TOKEN": "sekrit"}, monkeypatch
    )
    assert config.MCP_TRANSPORT == "streamable-http"
    assert config.MCP_HTTP_AUTH_TOKEN == "sekrit"


# --- server startup behavior (importing the real module) ---


@pytest.fixture
def real_server(monkeypatch):
    """Force a clean re-import of proxmox_mcp.server (bypassing the conftest mock)."""
    import sys

    for mod in [m for m in sys.modules if m.startswith("proxmox_mcp.server")]:
        del sys.modules[mod]
    with patch.dict(sys.modules):
        import proxmox_mcp.server as server

        yield server


def test_streamable_http_requires_auth_token(real_server, monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_HTTP_AUTH_TOKEN", "")
    # Rebuild the module-level config with the bad env.
    from proxmox_mcp.config import ProxmoxConfig

    real_server.config = ProxmoxConfig()
    with pytest.raises(RuntimeError, match="MCP_HTTP_AUTH_TOKEN"):
        real_server.main()


def test_stdio_startup_warns_on_unverified_tls(real_server, monkeypatch, caplog):
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("PROXMOX_VERIFY_SSL", "false")
    from proxmox_mcp.config import ProxmoxConfig

    real_server.config = ProxmoxConfig()
    with patch.object(real_server, "mcp") as mock_mcp:
        mock_mcp.run = lambda **kwargs: None
        real_server.main()
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("PROXMOX_VERIFY_SSL" in w and "MITM" in w for w in warnings)


def test_lazy_proxmox_client_is_stable_and_reusable(real_server):
    c1 = real_server.proxmox_client
    c2 = real_server.get_server_client()
    assert c1 is c2
    assert isinstance(c1, real_server.ProxmoxClient)


def test_http_app_accepts_bearer_middleware(real_server):
    from starlette.middleware.base import BaseHTTPMiddleware

    from proxmox_mcp.server import BearerTokenAuthMiddleware

    assert issubclass(BearerTokenAuthMiddleware, BaseHTTPMiddleware)
    app = real_server.mcp.streamable_http_app()
    app.add_middleware(BearerTokenAuthMiddleware, expected_token="tok")
    # The app must still be a runnable ASGI object after middleware is added.
    assert callable(app)
