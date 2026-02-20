# tests/test_integration.py
"""Integration tests requiring a live Proxmox instance. Skipped by default."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires live Proxmox instance")
class TestLiveCluster:
    async def test_cluster_status(self):
        """Test cluster status against real Proxmox."""
        pass

    async def test_list_nodes(self):
        """Test node listing against real Proxmox."""
        pass

    async def test_list_vms(self):
        """Test VM listing against real Proxmox."""
        pass
