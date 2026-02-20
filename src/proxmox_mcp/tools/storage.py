"""Storage management tools for Proxmox VE."""

import logging
from proxmox_mcp.utils.errors import format_error_response
from proxmox_mcp.utils.sanitizers import validate_storage_id
from proxmox_mcp.utils.validators import validate_node_name

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp():
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
        logger.error(f"Failed to list storage: {e}")
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
        logger.info(f"Fetching storage status for '{storage}' on node '{node}'")
        data = await client.api_call(client.api.nodes(node).storage(storage).status.get)

        return {
            "status": "success",
            "node": node,
            "storage": storage,
            "data": data,
        }
    except Exception as e:
        logger.error(f"Failed to get storage status for '{storage}' on '{node}': {e}")
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
            f"Listing content for storage '{storage}' on node '{node}' "
            f"(content_type={content_type})"
        )

        kwargs = {}
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
        logger.error(f"Failed to list content for storage '{storage}' on '{node}': {e}")
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
        logger.info(f"Fetching available ISOs from '{storage}' on node '{node}'")
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
        logger.error(f"Failed to get ISOs from '{storage}' on '{node}': {e}")
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
        logger.info(f"Fetching available templates from '{storage}' on node '{node}'")
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
        logger.error(f"Failed to get templates from '{storage}' on '{node}': {e}")
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
                Exception(
                    f"Invalid storage type '{storage_type}'. "
                    f"Valid types: {', '.join(sorted(VALID_STORAGE_TYPES))}"
                )
            )

        # Validate content types
        content_list = [c.strip() for c in content.split(",") if c.strip()]
        invalid_content = set(content_list) - VALID_CONTENT_TYPES
        if invalid_content:
            return format_error_response(
                Exception(
                    f"Invalid content types: {', '.join(invalid_content)}. "
                    f"Valid types: {', '.join(sorted(VALID_CONTENT_TYPES))}"
                )
            )

        # Check for duplicate storage ID
        existing = await client.api_call(client.api.storage.get)
        existing_ids = {s.get("storage") for s in existing}
        if storage_id in existing_ids:
            return format_error_response(
                Exception(f"Storage ID '{storage_id}' already exists."),
                suggestion="Choose a different storage ID or remove the existing one first.",
            )

        # Build API parameters
        api_params: dict = {
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
                return format_error_response(Exception("'path' is required for type=dir."))
            api_params["path"] = path
            if mkdir:
                api_params["mkdir"] = 1

        elif storage_type in ("lvm", "lvmthin"):
            if not vgname:
                return format_error_response(
                    Exception("'vgname' is required for type=lvm/lvmthin.")
                )
            api_params["vgname"] = vgname
            if storage_type == "lvmthin" and thinpool:
                api_params["thinpool"] = thinpool

        elif storage_type == "zfspool":
            if not pool:
                return format_error_response(Exception("'pool' is required for type=zfspool."))
            api_params["pool"] = pool
            if sparse:
                api_params["sparse"] = 1

        elif storage_type == "nfs":
            if not server or not export:
                return format_error_response(
                    Exception("'server' and 'export' are required for type=nfs.")
                )
            api_params["server"] = server
            api_params["export"] = export
            if nfs_options:
                api_params["options"] = nfs_options

        elif storage_type == "cifs":
            if not server or not share:
                return format_error_response(
                    Exception("'server' and 'share' are required for type=cifs.")
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
                Exception(
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
