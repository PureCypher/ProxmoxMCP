"""Tests for task tracking tools."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_client():
    """Create a mock ProxmoxClient with api_call as AsyncMock."""
    client = MagicMock()
    client.api_call = AsyncMock()
    client.validate_node = MagicMock()
    return client


# --- list_tasks ---


@pytest.mark.asyncio
async def test_list_tasks_single_node(mock_client):
    from proxmox_mcp.tools.task import list_tasks

    mock_client.api_call.return_value = [
        {
            "upid": "UPID:pve1:00001234:abcdef:6500ABCD:qmstart:100:root@pam:",
            "type": "qmstart",
            "status": "OK",
            "node": "pve1",
            "starttime": 1700000000,
        },
        {
            "upid": "UPID:pve1:00001235:abcdf0:6500ABCE:vzdump:101:root@pam:",
            "type": "vzdump",
            "status": "running",
            "node": "pve1",
            "starttime": 1700000100,
        },
    ]

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await list_tasks(node="pve1", limit=10)

    assert result["status"] == "success"
    assert result["node"] == "pve1"
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_list_tasks_all_nodes(mock_client):
    from proxmox_mcp.tools.task import list_tasks

    # First call returns nodes list, subsequent calls return tasks per node
    mock_client.api_call.side_effect = [
        # GET nodes
        [{"node": "pve1"}, {"node": "pve2"}],
        # GET nodes/pve1/tasks
        [
            {"upid": "UPID:pve1:001", "status": "OK", "type": "qmstart"},
        ],
        # GET nodes/pve2/tasks
        [
            {"upid": "UPID:pve2:001", "status": "running", "type": "vzdump"},
        ],
    ]

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await list_tasks()

    assert result["status"] == "success"
    assert result["node"] == "all"
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_list_tasks_with_status_filter_running(mock_client):
    from proxmox_mcp.tools.task import list_tasks

    mock_client.api_call.return_value = [
        {"upid": "UPID:pve1:001", "status": "OK", "type": "qmstart"},
        {"upid": "UPID:pve1:002", "status": "running", "type": "vzdump"},
        {"upid": "UPID:pve1:003", "status": "WARNINGS", "type": "qmstop"},
    ]

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await list_tasks(node="pve1", status_filter="running")

    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["tasks"][0]["status"] == "running"


@pytest.mark.asyncio
async def test_list_tasks_with_status_filter_completed(mock_client):
    from proxmox_mcp.tools.task import list_tasks

    mock_client.api_call.return_value = [
        {"upid": "UPID:pve1:001", "status": "OK", "type": "qmstart"},
        {"upid": "UPID:pve1:002", "status": "running", "type": "vzdump"},
    ]

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await list_tasks(node="pve1", status_filter="completed")

    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["tasks"][0]["status"] == "OK"


@pytest.mark.asyncio
async def test_list_tasks_with_status_filter_error(mock_client):
    from proxmox_mcp.tools.task import list_tasks

    mock_client.api_call.return_value = [
        {"upid": "UPID:pve1:001", "status": "OK", "type": "qmstart"},
        {"upid": "UPID:pve1:002", "status": "running", "type": "vzdump"},
        {"upid": "UPID:pve1:003", "status": "WARNINGS", "type": "qmstop"},
    ]

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await list_tasks(node="pve1", status_filter="error")

    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["tasks"][0]["status"] == "WARNINGS"


@pytest.mark.asyncio
async def test_list_tasks_error(mock_client):
    from proxmox_mcp.tools.task import list_tasks

    mock_client.api_call.side_effect = Exception("connection error")

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await list_tasks(node="pve1")

    assert result["status"] == "error"


# --- get_task_status ---


@pytest.mark.asyncio
async def test_get_task_status(mock_client):
    from proxmox_mcp.tools.task import get_task_status

    upid = "UPID:pve1:00001234:abcdef:6500ABCD:qmstart:100:root@pam:"
    mock_client.api_call.return_value = {
        "status": "running",
        "type": "qmstart",
        "pid": 1234,
        "node": "pve1",
        "user": "root@pam",
    }

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await get_task_status("pve1", upid)

    assert result["status"] == "success"
    assert result["upid"] == upid
    assert result["task_status"]["status"] == "running"
    mock_client.validate_node.assert_called_once_with("pve1")


@pytest.mark.asyncio
async def test_get_task_status_completed(mock_client):
    from proxmox_mcp.tools.task import get_task_status

    upid = "UPID:pve1:00001234:abcdef:6500ABCD:qmstart:100:root@pam:"
    mock_client.api_call.return_value = {
        "status": "stopped",
        "exitstatus": "OK",
        "type": "qmstart",
    }

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await get_task_status("pve1", upid)

    assert result["status"] == "success"
    assert result["task_status"]["exitstatus"] == "OK"


@pytest.mark.asyncio
async def test_get_task_status_error(mock_client):
    from proxmox_mcp.tools.task import get_task_status

    mock_client.api_call.side_effect = Exception("task not found")

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await get_task_status("pve1", "UPID:invalid")

    assert result["status"] == "error"


# --- get_task_log ---


@pytest.mark.asyncio
async def test_get_task_log(mock_client):
    from proxmox_mcp.tools.task import get_task_log

    upid = "UPID:pve1:00001234:abcdef:6500ABCD:qmstart:100:root@pam:"
    mock_client.api_call.return_value = [
        {"n": 1, "t": "starting VM 100"},
        {"n": 2, "t": "started VM 100"},
        {"n": 3, "t": "TASK OK"},
    ]

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await get_task_log("pve1", upid)

    assert result["status"] == "success"
    assert result["upid"] == upid
    assert result["count"] == 3
    assert result["log"][0]["t"] == "starting VM 100"


@pytest.mark.asyncio
async def test_get_task_log_empty(mock_client):
    from proxmox_mcp.tools.task import get_task_log

    mock_client.api_call.return_value = []

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await get_task_log("pve1", "UPID:pve1:001")

    assert result["status"] == "success"
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_get_task_log_error(mock_client):
    from proxmox_mcp.tools.task import get_task_log

    mock_client.api_call.side_effect = Exception("log not available")

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await get_task_log("pve1", "UPID:invalid")

    assert result["status"] == "error"


# --- wait_for_task ---


@pytest.mark.asyncio
async def test_wait_for_task_immediate_complete(mock_client):
    from proxmox_mcp.tools.task import wait_for_task

    upid = "UPID:pve1:00001234:abcdef:6500ABCD:qmstart:100:root@pam:"
    mock_client.api_call.return_value = {
        "status": "stopped",
        "exitstatus": "OK",
    }

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        result = await wait_for_task("pve1", upid, timeout=10, poll_interval=1)

    assert result["status"] == "success"
    assert result["task_status"]["exitstatus"] == "OK"
    assert result["elapsed_seconds"] == 0


@pytest.mark.asyncio
async def test_wait_for_task_completes_after_polls(mock_client):
    from proxmox_mcp.tools.task import wait_for_task

    upid = "UPID:pve1:00001234:abcdef:6500ABCD:qmstart:100:root@pam:"
    mock_client.api_call.side_effect = [
        {"status": "running"},
        {"status": "running"},
        {"status": "stopped", "exitstatus": "OK"},
    ]

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        with patch("proxmox_mcp.tools.task.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_task("pve1", upid, timeout=30, poll_interval=2)

    assert result["status"] == "success"
    assert result["task_status"]["exitstatus"] == "OK"
    assert result["elapsed_seconds"] == 4  # 2 polls * 2s interval


@pytest.mark.asyncio
async def test_wait_for_task_timeout(mock_client):
    from proxmox_mcp.tools.task import wait_for_task

    upid = "UPID:pve1:00001234:abcdef:6500ABCD:qmstart:100:root@pam:"
    # Always returns running
    mock_client.api_call.return_value = {"status": "running"}

    with patch("proxmox_mcp.tools.task.get_client", return_value=mock_client):
        with patch("proxmox_mcp.tools.task.asyncio.sleep", new_callable=AsyncMock):
            result = await wait_for_task("pve1", upid, timeout=4, poll_interval=2)

    assert result["status"] == "error"
    assert result["error_type"] == "TaskTimeoutError"
    assert "suggestion" in result
