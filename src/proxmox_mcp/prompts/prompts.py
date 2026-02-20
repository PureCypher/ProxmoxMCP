# src/proxmox_mcp/prompts/prompts.py
"""MCP prompt templates for common Proxmox workflows."""


def get_mcp():
    from proxmox_mcp.server import mcp
    return mcp


mcp = get_mcp()


@mcp.prompt()
def infrastructure_overview() -> str:
    """Generate a prompt for reviewing the current Proxmox infrastructure."""
    return (
        "Please provide a comprehensive overview of my Proxmox infrastructure:\n"
        "1. Cluster health and quorum status\n"
        "2. Node status (CPU/RAM utilization, uptime)\n"
        "3. VM summary (running vs stopped, resource allocation)\n"
        "4. Container summary\n"
        "5. Storage utilization across all pools\n"
        "6. Any warnings or issues detected\n"
        "Use the available tools to gather this information."
    )


@mcp.prompt()
def capacity_planning() -> str:
    """Generate a prompt for capacity planning analysis."""
    return (
        "Analyze the current Proxmox cluster capacity:\n"
        "1. Gather node resource utilization (CPU, RAM, storage)\n"
        "2. List all VMs and containers with their allocated resources\n"
        "3. Calculate over-commitment ratios for CPU and RAM\n"
        "4. Identify the most and least loaded nodes\n"
        "5. Recommend if additional capacity is needed\n"
        "6. Suggest VM migration opportunities for load balancing."
    )


@mcp.prompt()
def vm_deployment(name: str, purpose: str, os: str = "linux") -> str:
    """Generate a prompt for deploying a new VM with best practices."""
    return (
        f"Help me deploy a new VM with these requirements:\n"
        f"- Name: {name}\n"
        f"- Purpose: {purpose}\n"
        f"- OS: {os}\n"
        "Steps:\n"
        "1. Check available resources across nodes\n"
        "2. Select the best node based on current load\n"
        "3. Get the next available VMID\n"
        "4. Recommend appropriate resource allocation for the purpose\n"
        "5. Check available ISOs or templates\n"
        "6. Create the VM with best-practice configuration\n"
        "7. Verify creation was successful."
    )


@mcp.prompt()
def disaster_recovery_check() -> str:
    """Generate a prompt for disaster recovery readiness assessment."""
    return (
        "Assess the disaster recovery readiness of this Proxmox environment:\n"
        "1. List all VMs and containers with their last backup date\n"
        "2. Identify any VMs/CTs with no recent backups (>7 days)\n"
        "3. Check snapshot status across all VMs\n"
        "4. Review storage availability for backups\n"
        "5. List any backup jobs configured\n"
        "6. Provide recommendations for improving backup coverage."
    )


@mcp.prompt()
def security_audit() -> str:
    """Generate a prompt for a basic security audit of the Proxmox environment."""
    return (
        "Perform a basic security audit of the Proxmox environment:\n"
        "1. List all nodes and their kernel versions\n"
        "2. Review firewall rules on nodes and VMs\n"
        "3. Check for VMs with no firewall enabled\n"
        "4. List privileged containers (potential security risk)\n"
        "5. Review API access tokens and user permissions\n"
        "6. Identify any VMs/CTs exposed to external networks\n"
        "7. Provide security hardening recommendations."
    )


@mcp.prompt()
def troubleshoot_vm(vmid: int) -> str:
    """Generate a prompt for troubleshooting a problematic VM."""
    return (
        f"Troubleshoot VM {vmid}:\n"
        "1. Get current status and any error states\n"
        "2. Review the VM configuration for misconfigurations\n"
        "3. Check resource allocation vs actual usage (RRD data)\n"
        "4. Review recent tasks related to this VM for errors\n"
        "5. Check the node's syslog for relevant entries\n"
        "6. List snapshots and backup history\n"
        "7. Provide diagnosis and recommended actions."
    )
