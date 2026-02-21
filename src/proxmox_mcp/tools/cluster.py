"""Cluster-level tools for Proxmox VE."""

import logging

from proxmox_mcp.utils.errors import format_error_response

logger = logging.getLogger("proxmox-mcp")


def get_client():
    from proxmox_mcp.server import proxmox_client

    return proxmox_client


def get_mcp():
    from proxmox_mcp.server import mcp

    return mcp


mcp = get_mcp()


@mcp.tool()
async def get_cluster_status() -> dict:
    """Get the overall cluster status including cluster info and node membership.

    Returns cluster-level information (name, quorum, version) and a list of all
    nodes with their online/offline status.
    """
    try:
        client = get_client()
        logger.info("Fetching cluster status")
        data = await client.api_call(client.api.cluster.status.get)

        cluster_info = {}
        nodes = []
        for item in data:
            if item.get("type") == "cluster":
                cluster_info = {
                    "name": item.get("name"),
                    "version": item.get("version"),
                    "quorate": item.get("quorate"),
                    "nodes": item.get("nodes"),
                }
            elif item.get("type") == "node":
                nodes.append(
                    {
                        "name": item.get("name"),
                        "id": item.get("id"),
                        "online": item.get("online"),
                        "ip": item.get("ip"),
                        "level": item.get("level", ""),
                        "local": item.get("local", 0),
                    }
                )

        return {
            "status": "success",
            "cluster": cluster_info,
            "nodes": nodes,
        }
    except Exception as e:
        logger.error("Failed to get cluster status: %s", e)
        return format_error_response(e)


@mcp.tool()
async def get_cluster_resources(resource_type: str | None = None) -> dict:
    """Get all resources across the cluster with optional type filtering.

    Args:
        resource_type: Optional filter - one of 'vm', 'storage', 'node', 'sdn'.
                       If not provided, returns all resource types.
    """
    try:
        client = get_client()
        logger.info("Fetching cluster resources (type=%s)", resource_type)
        kwargs = {}
        if resource_type:
            kwargs["type"] = resource_type
        data = await client.api_call(client.api.cluster.resources.get, **kwargs)

        return {
            "status": "success",
            "resource_type": resource_type or "all",
            "count": len(data),
            "resources": data,
        }
    except Exception as e:
        logger.error("Failed to get cluster resources: %s", e)
        return format_error_response(e)


@mcp.tool()
async def get_cluster_log(max_entries: int = 50) -> dict:
    """Get recent cluster log entries.

    Args:
        max_entries: Maximum number of log entries to return (default: 50).
    """
    try:
        client = get_client()
        logger.info("Fetching cluster log (max_entries=%d)", max_entries)
        data = await client.api_call(client.api.cluster.log.get, max=max_entries)

        return {
            "status": "success",
            "count": len(data),
            "entries": data,
        }
    except Exception as e:
        logger.error("Failed to get cluster log: %s", e)
        return format_error_response(e)


@mcp.tool()
async def get_next_vmid() -> dict:
    """Get the next available VMID from the cluster.

    Returns the next free VMID that can be used when creating a new VM or container.
    """
    try:
        client = get_client()
        logger.info("Fetching next available VMID")
        data = await client.api_call(client.api.cluster.nextid.get)

        return {
            "status": "success",
            "vmid": int(data),
        }
    except Exception as e:
        logger.error("Failed to get next VMID: %s", e)
        return format_error_response(e)


@mcp.tool()
async def list_pools() -> dict:
    """List all resource pools in the cluster.

    Returns a list of pools with their comments and member counts.
    """
    try:
        client = get_client()
        logger.info("Fetching resource pools")
        data = await client.api_call(client.api.pools.get)

        return {
            "status": "success",
            "count": len(data),
            "pools": data,
        }
    except Exception as e:
        logger.error("Failed to list pools: %s", e)
        return format_error_response(e)


@mcp.tool()
async def create_pool(poolid: str, comment: str | None = None) -> dict:
    """Create a new resource pool.

    Args:
        poolid: Unique pool identifier (e.g. 'production', 'dev-team').
        comment: Optional description for the pool.
    """
    try:
        client = get_client()
        if client.is_dry_run:
            return client.dry_run_response("create_pool", poolid=poolid)
        kwargs = {"poolid": poolid}
        if comment:
            kwargs["comment"] = comment
        logger.info("Creating resource pool '%s'", poolid)
        await client.api_call(client.api.pools.post, **kwargs)
        return {
            "status": "success",
            "poolid": poolid,
            "message": f"Pool '{poolid}' created successfully.",
        }
    except Exception as e:
        logger.error("Failed to create pool '%s': %s", poolid, e)
        return format_error_response(e)


@mcp.tool()
async def modify_pool(
    poolid: str,
    comment: str | None = None,
    vms: str | None = None,
    storage: str | None = None,
    delete: bool = False,
) -> dict:
    """Modify a resource pool — add/remove members or update comment.

    Args:
        poolid: The pool to modify.
        comment: New comment/description for the pool.
        vms: Comma-separated VMIDs to add or remove (e.g. '100,101').
        storage: Comma-separated storage IDs to add or remove.
        delete: If True, remove the specified vms/storage instead of adding.
    """
    try:
        client = get_client()
        if client.is_dry_run:
            return client.dry_run_response("modify_pool", poolid=poolid)
        kwargs: dict = {}
        if comment is not None:
            kwargs["comment"] = comment
        if vms:
            kwargs["vms"] = vms
        if storage:
            kwargs["storage"] = storage
        if delete:
            kwargs["delete"] = 1
        if not kwargs:
            return format_error_response(
                Exception("No changes specified for pool modification.")
            )
        logger.info("Modifying pool '%s': %s", poolid, list(kwargs.keys()))
        await client.api_call(client.api.pools(poolid).put, **kwargs)
        return {
            "status": "success",
            "poolid": poolid,
            "changes": list(kwargs.keys()),
        }
    except Exception as e:
        logger.error("Failed to modify pool '%s': %s", poolid, e)
        return format_error_response(e)


@mcp.tool()
async def delete_pool(poolid: str, confirm: bool = False) -> dict:
    """Delete a resource pool. Set confirm=True to execute.

    The pool must be empty (no VMs or storage assigned).

    Args:
        poolid: The pool to delete.
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete resource pool '{poolid}'.",
                "action": "Call delete_pool again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_pool", poolid=poolid)
        logger.warning("Deleting resource pool '%s'", poolid)
        await client.api_call(client.api.pools(poolid).delete)
        return {
            "status": "success",
            "poolid": poolid,
            "message": f"Pool '{poolid}' deleted successfully.",
        }
    except Exception as e:
        logger.error("Failed to delete pool '%s': %s", poolid, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# User and permission management
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_users() -> dict:
    """List all users in the Proxmox cluster.

    Returns each user's ID, realm, email, enabled status, and groups.
    """
    try:
        client = get_client()
        logger.info("Listing all users")
        data = await client.api_call(client.api.access.users.get)
        return {"status": "success", "count": len(data), "users": data}
    except Exception as e:
        logger.error("Failed to list users: %s", e)
        return format_error_response(e)


@mcp.tool()
async def create_user(
    userid: str,
    password: str | None = None,
    email: str | None = None,
    firstname: str | None = None,
    lastname: str | None = None,
    groups: str | None = None,
    comment: str | None = None,
    enable: bool = True,
) -> dict:
    """Create a new user.

    Args:
        userid: User ID in 'user@realm' format (e.g. 'john@pve', 'admin@pam').
        password: Password (required for PVE realm, not for PAM/LDAP).
        email: User email address.
        firstname: First name.
        lastname: Last name.
        groups: Comma-separated group names.
        comment: User comment/description.
        enable: Enable the user (default True).
    """
    try:
        client = get_client()
        if client.is_dry_run:
            return client.dry_run_response("create_user", userid=userid)
        kwargs: dict = {"userid": userid, "enable": 1 if enable else 0}
        if password:
            kwargs["password"] = password
        if email:
            kwargs["email"] = email
        if firstname:
            kwargs["firstname"] = firstname
        if lastname:
            kwargs["lastname"] = lastname
        if groups:
            kwargs["groups"] = groups
        if comment:
            kwargs["comment"] = comment
        logger.info("Creating user '%s'", userid)
        await client.api_call(client.api.access.users.post, **kwargs)
        return {
            "status": "success",
            "userid": userid,
            "message": f"User '{userid}' created successfully.",
        }
    except Exception as e:
        logger.error("Failed to create user '%s': %s", userid, e)
        return format_error_response(e)


@mcp.tool()
async def delete_user(userid: str, confirm: bool = False) -> dict:
    """Delete a user. Set confirm=True to execute.

    Args:
        userid: User ID to delete (e.g. 'john@pve').
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": f"This will delete user '{userid}'.",
                "action": "Call delete_user again with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_user", userid=userid)
        logger.warning("Deleting user '%s'", userid)
        await client.api_call(client.api.access.users(userid).delete)
        return {
            "status": "success",
            "userid": userid,
            "message": f"User '{userid}' deleted.",
        }
    except Exception as e:
        logger.error("Failed to delete user '%s': %s", userid, e)
        return format_error_response(e)


@mcp.tool()
async def list_roles() -> dict:
    """List all available roles in the Proxmox cluster.

    Returns each role's ID and associated privileges.
    """
    try:
        client = get_client()
        logger.info("Listing all roles")
        data = await client.api_call(client.api.access.roles.get)
        return {"status": "success", "count": len(data), "roles": data}
    except Exception as e:
        logger.error("Failed to list roles: %s", e)
        return format_error_response(e)


@mcp.tool()
async def set_user_permission(
    path: str,
    roles: str,
    users: str | None = None,
    groups: str | None = None,
    propagate: bool = True,
) -> dict:
    """Set access control permissions (ACL).

    Args:
        path: ACL path (e.g. '/', '/vms/100', '/storage/local', '/pool/dev').
        roles: Comma-separated role names (e.g. 'PVEVMUser', 'PVEAdmin').
        users: Comma-separated user IDs to grant (e.g. 'john@pve').
        groups: Comma-separated group names to grant.
        propagate: Propagate to child objects (default True).
    """
    try:
        client = get_client()
        if not users and not groups:
            return format_error_response(
                Exception("Must specify either 'users' or 'groups' (or both).")
            )
        if client.is_dry_run:
            return client.dry_run_response(
                "set_user_permission", path=path, roles=roles
            )
        kwargs: dict = {"path": path, "roles": roles, "propagate": 1 if propagate else 0}
        if users:
            kwargs["users"] = users
        if groups:
            kwargs["groups"] = groups
        logger.info("Setting ACL on '%s': roles=%s", path, roles)
        await client.api_call(client.api.access.acl.put, **kwargs)
        return {
            "status": "success",
            "path": path,
            "roles": roles,
            "users": users,
            "groups": groups,
        }
    except Exception as e:
        logger.error("Failed to set ACL on '%s': %s", path, e)
        return format_error_response(e)


# ---------------------------------------------------------------------------
# HA (High Availability) resource management
# ---------------------------------------------------------------------------

VALID_HA_STATES = frozenset({"started", "stopped", "disabled", "ignored"})


@mcp.tool()
async def list_ha_resources() -> dict:
    """List all HA-managed resources in the cluster.

    Returns each resource's SID, state, group, and settings.
    """
    try:
        client = get_client()
        logger.info("Listing HA resources")
        data = await client.api_call(client.api.cluster.ha.resources.get)
        return {"status": "success", "count": len(data), "resources": data}
    except Exception as e:
        logger.error("Failed to list HA resources: %s", e)
        return format_error_response(e)


@mcp.tool()
async def create_ha_resource(
    sid: str,
    state: str = "started",
    group: str | None = None,
    max_restart: int | None = None,
    max_relocate: int | None = None,
    comment: str | None = None,
) -> dict:
    """Add a VM/CT to HA management.

    Args:
        sid: Service ID in 'type:vmid' format (e.g. 'vm:100', 'ct:200').
        state: Desired state - 'started', 'stopped', 'disabled', 'ignored'.
        group: HA group to assign to.
        max_restart: Max restart attempts on failure (default: cluster setting).
        max_relocate: Max relocations on failure (default: cluster setting).
        comment: Resource comment/description.
    """
    try:
        client = get_client()
        if state not in VALID_HA_STATES:
            return format_error_response(
                Exception(
                    f"Invalid state '{state}'. "
                    f"Must be one of: {', '.join(sorted(VALID_HA_STATES))}"
                )
            )
        if client.is_dry_run:
            return client.dry_run_response("create_ha_resource", sid=sid, state=state)
        kwargs: dict = {"sid": sid, "state": state}
        if group:
            kwargs["group"] = group
        if max_restart is not None:
            kwargs["max_restart"] = max_restart
        if max_relocate is not None:
            kwargs["max_relocate"] = max_relocate
        if comment:
            kwargs["comment"] = comment
        logger.info("Adding HA resource '%s' with state '%s'", sid, state)
        await client.api_call(client.api.cluster.ha.resources.post, **kwargs)
        return {
            "status": "success",
            "sid": sid,
            "state": state,
            "message": f"HA resource '{sid}' created.",
        }
    except Exception as e:
        logger.error("Failed to create HA resource '%s': %s", sid, e)
        return format_error_response(e)


@mcp.tool()
async def modify_ha_resource(
    sid: str,
    state: str | None = None,
    group: str | None = None,
    max_restart: int | None = None,
    max_relocate: int | None = None,
    comment: str | None = None,
) -> dict:
    """Modify an existing HA resource.

    Args:
        sid: Service ID (e.g. 'vm:100').
        state: New desired state - 'started', 'stopped', 'disabled', 'ignored'.
        group: HA group to assign to.
        max_restart: Max restart attempts.
        max_relocate: Max relocations.
        comment: Resource comment.
    """
    try:
        client = get_client()
        if state is not None and state not in VALID_HA_STATES:
            return format_error_response(
                Exception(
                    f"Invalid state '{state}'. "
                    f"Must be one of: {', '.join(sorted(VALID_HA_STATES))}"
                )
            )
        if client.is_dry_run:
            return client.dry_run_response("modify_ha_resource", sid=sid)
        kwargs: dict = {}
        if state is not None:
            kwargs["state"] = state
        if group is not None:
            kwargs["group"] = group
        if max_restart is not None:
            kwargs["max_restart"] = max_restart
        if max_relocate is not None:
            kwargs["max_relocate"] = max_relocate
        if comment is not None:
            kwargs["comment"] = comment
        if not kwargs:
            return format_error_response(
                Exception("No changes specified for HA resource.")
            )
        logger.info("Modifying HA resource '%s': %s", sid, list(kwargs.keys()))
        await client.api_call(client.api.cluster.ha.resources(sid).put, **kwargs)
        return {
            "status": "success",
            "sid": sid,
            "changes": list(kwargs.keys()),
        }
    except Exception as e:
        logger.error("Failed to modify HA resource '%s': %s", sid, e)
        return format_error_response(e)


@mcp.tool()
async def delete_ha_resource(sid: str, confirm: bool = False) -> dict:
    """Remove a VM/CT from HA management. Set confirm=True to execute.

    This does NOT delete the VM/CT, only removes it from HA.

    Args:
        sid: Service ID (e.g. 'vm:100').
        confirm: Must be True to execute.
    """
    try:
        client = get_client()
        if not confirm:
            return {
                "status": "confirmation_required",
                "warning": (
                    f"This will remove '{sid}' from HA management. "
                    f"The VM/CT itself will NOT be deleted."
                ),
                "action": "Call delete_ha_resource with confirm=True to proceed.",
            }
        if client.is_dry_run:
            return client.dry_run_response("delete_ha_resource", sid=sid)
        logger.warning("Removing HA resource '%s'", sid)
        await client.api_call(client.api.cluster.ha.resources(sid).delete)
        return {
            "status": "success",
            "sid": sid,
            "message": f"HA resource '{sid}' removed.",
        }
    except Exception as e:
        logger.error("Failed to delete HA resource '%s': %s", sid, e)
        return format_error_response(e)
