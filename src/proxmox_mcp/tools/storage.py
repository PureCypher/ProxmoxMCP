"""Storage management tools for Proxmox VE."""

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from proxmox_mcp.utils.errors import InvalidParameterError, format_error_response
from proxmox_mcp.utils.formatters import format_task_result
from proxmox_mcp.utils.sanitizers import validate_storage_id
from proxmox_mcp.utils.validators import validate_node_name

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from proxmox_mcp.client import ProxmoxClient

logger = logging.getLogger("proxmox-mcp")


def get_client() -> "ProxmoxClient":
    from proxmox_mcp.server import get_server_client

    return get_server_client()


def get_mcp() -> "FastMCP":
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()


@mcp.tool()
async def list_storage() -> dict:
    """List all storage backends configured in the Proxmox cluster.

    Returns each storage's name, type, content types, nodes, and shared status.
    """
    try:
        client = get_client()
        logger.info("Listing all cluster storage")
        data = await client.api_call(client.api.storage.get)

        return {
            "status": "success",
            "count": len(data),
            "storage": data,
        }
    except Exception as e:
        logger.error("Failed to list storage: %s", e)
        return format_error_response(e)


@mcp.tool()
async def get_storage_status(node: str, storage: str) -> dict:
    """Get detailed status and usage information for a specific storage on a node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        storage: The storage identifier (e.g., 'local', 'local-lvm', 'ceph-pool').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info("Fetching storage status for '%s' on node '%s'", storage, node)
        data = await client.api_call(client.api.nodes(node).storage(storage).status.get)

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "data": data,
        }
    except Exception as e:
        logger.error("Failed to get storage status for '%s' on '%s': %s", storage, node, e)
        return format_error_response(e)


@mcp.tool()
async def list_storage_content(node: str, storage: str, content_type: str | None = None) -> dict:
    """List the contents of a specific storage on a node.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        storage: The storage identifier (e.g., 'local', 'local-lvm').
        content_type: Optional filter for content type (e.g., 'images', 'iso',
                      'vztmpl', 'backup', 'rootdir', 'snippets').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(
            "Listing content for storage '%s' on node '%s' (content_type=%s)",
            storage,
            node,
            content_type,
        )

        kwargs: dict[str, Any] = {}
        if content_type:
            kwargs["content"] = content_type

        data = await client.api_call(client.api.nodes(node).storage(storage).content.get, **kwargs)

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "content_type": content_type or "all",
            "count": len(data),
            "content": data,
        }
    except Exception as e:
        logger.error("Failed to list content for storage '%s' on '%s': %s", storage, node, e)
        return format_error_response(e)


@mcp.tool()
async def get_available_isos(node: str, storage: str = "local") -> dict:
    """List available ISO images on a specific storage.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        storage: The storage identifier (default: 'local').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info("Fetching available ISOs from '%s' on node '%s'", storage, node)
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, content="iso"
        )

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "count": len(data),
            "isos": data,
        }
    except Exception as e:
        logger.error("Failed to get ISOs from '%s' on '%s': %s", storage, node, e)
        return format_error_response(e)


@mcp.tool()
async def get_available_templates(node: str, storage: str = "local") -> dict:
    """List available container templates on a specific storage.

    Args:
        node: The name of the Proxmox node (e.g., 'pve1').
        storage: The storage identifier (default: 'local').
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info("Fetching available templates from '%s' on node '%s'", storage, node)
        data = await client.api_call(
            client.api.nodes(node).storage(storage).content.get, content="vztmpl"
        )

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "count": len(data),
            "templates": data,
        }
    except Exception as e:
        logger.error("Failed to get templates from '%s' on '%s': %s", storage, node, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# Storage configuration management (add / remove)
# ---------------------------------------------------------------------------

VALID_STORAGE_TYPES = frozenset({"dir", "lvm", "lvmthin", "zfspool", "nfs", "cifs", "btrfs"})
VALID_CONTENT_TYPES = frozenset(
    {
        "images",
        "rootdir",
        "vztmpl",
        "backup",
        "iso",
        "snippets",
        "import",
    }
)
DEFAULT_STORAGE_IDS = frozenset({"local", "local-lvm"})


@mcp.tool()
async def add_storage(
    storage_id: str,
    storage_type: str,
    content: str,
    path: str | None = None,
    nodes: str | None = None,
    shared: bool = False,
    disable: bool = False,
    vgname: str | None = None,
    thinpool: str | None = None,
    pool: str | None = None,
    server: str | None = None,
    export: str | None = None,
    share: str | None = None,
    username: str | None = None,
    password: str | None = None,
    domain: str | None = None,
    nfs_options: str | None = None,
    sparse: bool = True,
    mkdir: bool = True,
) -> dict:
    """Register a new storage resource in Proxmox VE configuration.

    Makes a mounted filesystem, NFS share, LVM volume group, or other storage
    backend available to Proxmox for VM/CT disks, backups, ISOs, etc.

    Args:
        storage_id: Unique identifier (e.g., 'local-data'). Alphanumeric, hyphens, underscores.
        storage_type: Backend type: 'dir', 'lvm', 'lvmthin', 'zfspool', 'nfs', 'cifs', 'btrfs'.
        content: Comma-separated content types (e.g., 'images,iso,vztmpl').
            Valid types: images, rootdir, vztmpl, backup, iso, snippets.
        path: Filesystem path for type=dir (must already be mounted).
        nodes: Comma-separated node names to restrict storage to. Empty = all nodes.
        shared: Mark as shared storage (accessible from all nodes).
        disable: Create in disabled state.
        vgname: LVM volume group name (for type=lvm or lvmthin).
        thinpool: LVM thin pool name (for type=lvmthin).
        pool: ZFS pool/dataset name (for type=zfspool).
        server: Server hostname or IP (for type=nfs or cifs).
        export: NFS export path (for type=nfs).
        share: CIFS share name (for type=cifs).
        username: CIFS username (for type=cifs).
        password: CIFS password (for type=cifs).
        domain: CIFS domain (for type=cifs).
        nfs_options: NFS mount options (for type=nfs).
        sparse: Use thin provisioning (for type=zfspool).
        mkdir: Create directory if it doesn't exist (for type=dir).
    """
    try:
        client = get_client()

        # Validate storage_id
        validate_storage_id(storage_id)

        # Validate storage type
        if storage_type not in VALID_STORAGE_TYPES:
            return format_error_response(
                InvalidParameterError(
                    f"Invalid storage type '{storage_type}'. "
                    f"Valid types: {', '.join(sorted(VALID_STORAGE_TYPES))}"
                )
            )

        # Validate content types
        content_list = [c.strip() for c in content.split(",") if c.strip()]
        invalid_content = set(content_list) - VALID_CONTENT_TYPES
        if invalid_content:
            return format_error_response(
                InvalidParameterError(
                    f"Invalid content types: {', '.join(invalid_content)}. "
                    f"Valid types: {', '.join(sorted(VALID_CONTENT_TYPES))}"
                )
            )

        # Check for duplicate storage ID
        existing = await client.api_call(client.api.storage.get)
        existing_ids = {s.get("storage") for s in existing}
        if storage_id in existing_ids:
            return format_error_response(
                InvalidParameterError(f"Storage ID '{storage_id}' already exists."),
                suggestion="Choose a different storage ID or remove the existing one first.",
            )

        # Build API parameters
        api_params: dict[str, Any] = {
            "storage": storage_id,
            "type": storage_type,
            "content": ",".join(content_list),
        }

        if nodes:
            api_params["nodes"] = nodes
        if shared:
            api_params["shared"] = 1
        if disable:
            api_params["disable"] = 1

        # Type-specific parameters
        if storage_type == "dir":
            if not path:
                return format_error_response(
                    InvalidParameterError("'path' is required for type=dir.")
                )
            api_params["path"] = path
            if mkdir:
                api_params["mkdir"] = 1

        elif storage_type in ("lvm", "lvmthin"):
            if not vgname:
                return format_error_response(
                    InvalidParameterError("'vgname' is required for type=lvm/lvmthin.")
                )
            api_params["vgname"] = vgname
            if storage_type == "lvmthin" and thinpool:
                api_params["thinpool"] = thinpool

        elif storage_type == "zfspool":
            if not pool:
                return format_error_response(
                    InvalidParameterError("'pool' is required for type=zfspool.")
                )
            api_params["pool"] = pool
            if sparse:
                api_params["sparse"] = 1

        elif storage_type == "nfs":
            if not server or not export:
                return format_error_response(
                    InvalidParameterError("'server' and 'export' are required for type=nfs.")
                )
            api_params["server"] = server
            api_params["export"] = export
            if nfs_options:
                api_params["options"] = nfs_options

        elif storage_type == "cifs":
            if not server or not share:
                return format_error_response(
                    InvalidParameterError("'server' and 'share' are required for type=cifs.")
                )
            api_params["server"] = server
            api_params["share"] = share
            if username:
                api_params["username"] = username
            if password:
                api_params["password"] = password
            if domain:
                api_params["domain"] = domain

        if client.is_dry_run:
            return client.dry_run_response("add_storage", **api_params)

        logger.warning(
            "Adding storage '%s' (type=%s, content=%s)",
            storage_id,
            storage_type,
            content,
        )

        await client.api_call(client.api.storage.post, **api_params)

        return {
            "status": "success",
            "storage_id": storage_id,
            "type": storage_type,
            "content": content_list,
            "proxmox_config": api_params,
        }
    except Exception as e:
        logger.error("Failed to add storage '%s': %s", storage_id, e)
        return format_error_response(e)


@mcp.tool()
async def remove_storage(
    storage_id: str,
    confirm: bool = False,
) -> dict:
    """Remove a storage configuration from Proxmox. Does NOT delete data.

    Only unregisters the storage from Proxmox configuration. The underlying
    data (files, LVM volumes, ZFS datasets) remains untouched.

    Args:
        storage_id: Storage identifier to remove.
        confirm: Must be True to proceed. Will fail if storage contains active VM/CT disks.
    """
    try:
        client = get_client()
        validate_storage_id(storage_id)

        # Never remove default storage
        if storage_id in DEFAULT_STORAGE_IDS:
            return format_error_response(
                InvalidParameterError(
                    f"Cannot remove default storage '{storage_id}'. "
                    f"This is a Proxmox default and should not be removed."
                )
            )

        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will unregister storage '{storage_id}' from Proxmox. "
                    f"Data on the storage will NOT be deleted, but Proxmox will "
                    f"no longer manage it."
                ),
                "action": "Call remove_storage again with confirm=True to proceed.",
                "storage_id": storage_id,
            }

        if client.is_dry_run:
            return client.dry_run_response("remove_storage", storage_id=storage_id)

        logger.warning("Removing storage configuration '%s'", storage_id)

        await client.api_call(client.api.storage(storage_id).delete)

        return {
            "status": "success",
            "storage_id": storage_id,
            "message": (
                f"Storage '{storage_id}' has been removed from Proxmox configuration. "
                f"Underlying data has NOT been deleted."
            ),
        }
    except Exception as e:
        logger.error("Failed to remove storage '%s': %s", storage_id, e)
        return format_error_response(e)


VALID_DOWNLOAD_CONTENT = frozenset({"iso", "vztmpl"})


@mcp.tool()
async def download_to_storage(
    node: str,
    storage: str,
    url: str,
    content: str,
    filename: str,
    verify_certificates: bool = True,
) -> dict:
    """Download an ISO or container template from a URL to storage.

    The URL is fetched by the Proxmox node (node-side), so for SSRF safety
    only 'http' and 'https' URLs are accepted; loopback (127.0.0.0/8, ::1),
    link-local (169.254.0.0/8), and '.local' hosts are rejected.

    Args:
        node: The node to download on.
        storage: Target storage (e.g. 'local').
        url: http:// or https:// URL to download from.
        content: Content type - 'iso' or 'vztmpl'.
        filename: Filename to save as (e.g. 'ubuntu-24.04.iso').
        verify_certificates: Verify SSL certificates (default True).
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https"):
            return format_error_response(
                InvalidParameterError(f"URL must use http or https scheme, got '{parsed.scheme}'.")
            )
        host = (parsed.hostname or "").lower()
        is_restricted_host = (
            host.startswith("127.")
            or host == "localhost"
            or host == "::1"
            or host.startswith("169.254.")
        )
        if is_restricted_host:
            return format_error_response(
                InvalidParameterError(
                    f"URL host '{host}' is loopback/link-local and is not allowed "
                    f"for node-side downloads."
                )
            )
        if host.endswith(".local"):
            return format_error_response(
                InvalidParameterError(
                    f"URL host '{host}' is a mDNS '.local' name and is not "
                    f"allowed for node-side downloads."
                )
            )
        if content not in VALID_DOWNLOAD_CONTENT:
            return format_error_response(
                InvalidParameterError(
                    f"Invalid content type '{content}'. Must be 'iso' or 'vztmpl'."
                )
            )
        if client.is_dry_run:
            return client.dry_run_response(
                "download_to_storage",
                node=node,
                storage=storage,
                url=url,
                filename=filename,
            )
        kwargs: dict[str, Any] = {
            "url": url,
            "content": content,
            "filename": filename,
        }
        if not verify_certificates:
            kwargs["verify-certificates"] = 0
        logger.info(
            "Downloading %s to '%s' on node '%s' from %s",
            content,
            storage,
            node,
            url,
        )
        upid = await client.api_call(
            client.api.nodes(node).storage(storage)("download-url").post,
            **kwargs,
        )
        return format_task_result({"data": upid})
    except Exception as e:
        logger.error("Failed to download to storage '%s': %s", storage, e)
        return format_error_response(e)
