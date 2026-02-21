"""Task tracking tools for Proxmox VE."""

import asyncio
import logging

from proxmox_mcp.utils.errors import TaskTimeoutError, format_error_response
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
async def list_tasks(
    node: str | None = None,
    limit: int = 20,
    status_filter: str | None = None,
) -> dict:
    """List recent tasks across the cluster or on a specific node.

    Args:
        node: Optional node name to filter tasks. If not provided, queries all nodes.
        limit: Maximum number of tasks to return per node (default: 20).
        status_filter: Optional filter - 'running', 'completed', or 'error'.
    """
    try:
        client = get_client()

        if node:
            validate_node_name(node)
            client.validate_node(node)
            logger.info("Listing tasks for node '%s' (limit=%d)", node, limit)
            data = await client.api_call(client.api.nodes(node).tasks.get, limit=limit)
        else:
            logger.info("Listing tasks across all nodes (limit=%d)", limit)
            # Get all nodes, then query tasks from each
            nodes_data = await client.api_call(client.api.nodes.get)
            data = []
            for n in nodes_data:
                node_name = n.get("node")
                try:
                    node_tasks = await client.api_call(
                        client.api.nodes(node_name).tasks.get, limit=limit
                    )
                    data.extend(node_tasks)
                except Exception as e:
                    logger.warning("Failed to get tasks from node '%s': %s", node_name, e)

        # Apply status filter if provided
        if status_filter:
            status_filter_lower = status_filter.lower()
            filtered = []
            for task in data:
                task_status = task.get("status", "").lower()
                if status_filter_lower == "running" and task_status == "running":
                    filtered.append(task)
                elif status_filter_lower == "completed" and task_status == "ok":
                    filtered.append(task)
                elif status_filter_lower == "error" and task_status not in (
                    "running",
                    "ok",
                    "",
                ):
                    filtered.append(task)
            data = filtered

        return {
            "status": "success",
            "node": node or "all",
            "count": len(data),
            "tasks": data,
        }
    except Exception as e:
        logger.error("Failed to list tasks: %s", e)
        return format_error_response(e)


@mcp.tool()
async def get_task_status(node: str, upid: str) -> dict:
    """Get the current status of a specific Proxmox task.

    Args:
        node: The node where the task is running.
        upid: The unique process ID (UPID) of the task.
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info("Fetching task status for UPID '%s' on node '%s'", upid, node)
        data = await client.api_call(client.api.nodes(node).tasks(upid).status.get)

        return {
            "status": "success",
            "node": node,
            "upid": upid,
            "task_status": data,
        }
    except Exception as e:
        logger.error("Failed to get task status for '%s': %s", upid, e)
        return format_error_response(e)


@mcp.tool()
async def get_task_log(node: str, upid: str, limit: int = 100) -> dict:
    """Get the log output of a specific Proxmox task.

    Args:
        node: The node where the task is/was running.
        upid: The unique process ID (UPID) of the task.
        limit: Maximum number of log lines to return (default: 100).
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info("Fetching task log for UPID '%s' on node '%s'", upid, node)
        data = await client.api_call(client.api.nodes(node).tasks(upid).log.get, limit=limit)

        return {
            "status": "success",
            "node": node,
            "upid": upid,
            "count": len(data),
            "log": data,
        }
    except Exception as e:
        logger.error("Failed to get task log for '%s': %s", upid, e)
        return format_error_response(e)


@mcp.tool()
async def wait_for_task(node: str, upid: str, timeout: int = 300, poll_interval: int = 5) -> dict:
    """Wait for a Proxmox task to complete, polling at regular intervals.

    Args:
        node: The node where the task is running.
        upid: The unique process ID (UPID) of the task.
        timeout: Maximum time to wait in seconds (default: 300).
        poll_interval: Seconds between status checks (default: 5).

    Returns the final task status once completed, or raises a timeout error.
    """
    try:
        validate_node_name(node)
        client = get_client()
        client.validate_node(node)
        logger.info(
            "Waiting for task '%s' on node '%s' (timeout=%ds, poll_interval=%ds)",
            upid, node, timeout, poll_interval,
        )

        elapsed = 0
        while elapsed < timeout:
            data = await client.api_call(client.api.nodes(node).tasks(upid).status.get)
            task_status = data.get("status", "")

            if task_status != "running":
                logger.info("Task '%s' completed with status: %s", upid, task_status)
                return {
                    "status": "success",
                    "node": node,
                    "upid": upid,
                    "task_status": data,
                    "elapsed_seconds": elapsed,
                }

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TaskTimeoutError(f"Task '{upid}' did not complete within {timeout} seconds.")
    except TaskTimeoutError:
        logger.warning("Task '%s' timed out after %ds", upid, timeout)
        return format_error_response(
            TaskTimeoutError(f"Task '{upid}' did not complete within {timeout} seconds."),
            suggestion=(
                "Increase the timeout or check the task status manually "
                "with get_task_status."
            ),
        )
    except Exception as e:
        logger.error("Failed while waiting for task '%s': %s", upid, e)
        return format_error_response(e)
