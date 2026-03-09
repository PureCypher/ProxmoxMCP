"""Input sanitization and validation for disk management tools."""

import re

from proxmox_mcp.utils.errors import InvalidParameterError

# Strict patterns for shell-interpolated values
# Whole disks: /dev/sda, /dev/vdb, /dev/nvme0n1 (NOT /dev/sdb1, /dev/nvme0n1p1)
DEVICE_PATH_RE = re.compile(r"^/dev/(?:[a-z]+|nvme\d+n\d+)$")
# Partitions: /dev/sdb1, /dev/nvme0n1p1, or whole disks
PARTITION_PATH_RE = re.compile(r"^/dev/(?:[a-z]+\d*|nvme\d+n\d+(?:p\d+)?)$")
MOUNT_PATH_RE = re.compile(r"^/(mnt|srv|media)/[a-zA-Z0-9_][a-zA-Z0-9_/\-]*$")
STORAGE_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]{0,63}$")
LABEL_RE = re.compile(r"^[a-zA-Z0-9_\-]{0,16}$")
SAFE_OPTION_RE = re.compile(r"^[a-zA-Z0-9_=,.\- ]+$")

# Shell metacharacters that must never appear in parameters
SHELL_METACHAR_RE = re.compile(r"[;|&$`\\'\"\(\)\{\}<>!~#\n\r]")

# Allowed mount options (validated individually)
ALLOWED_MOUNT_OPTIONS = frozenset(
    {
        "defaults",
        "noatime",
        "relatime",
        "noexec",
        "nosuid",
        "nodev",
        "ro",
        "rw",
        "nofail",
        "discard",
        "barrier=0",
        "barrier=1",
        "data=ordered",
        "data=writeback",
        "data=journal",
        "errors=remount-ro",
        "errors=continue",
        "x-systemd.automount",
    }
)

# Allowed mkfs options (flag + optional value)
ALLOWED_MKFS_FLAGS = frozenset(
    {
        "-m",
        "-L",
        "-n",
        "-b",
        "-i",
        "-N",
        "-O",
        "-T",
        "-E",
        "-f",
    }
)

# System-critical mount paths that must never be targets
CRITICAL_PATHS = frozenset(
    {
        "/",
        "/etc",
        "/var",
        "/home",
        "/usr",
        "/boot",
        "/tmp",
        "/root",
        "/opt",
        "/lib",
        "/bin",
        "/sbin",
        "/proc",
        "/sys",
        "/dev",
        "/run",
        "/boot/efi",
        "/var/log",
        "/var/lib",
    }
)

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

SNAPNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-\.]{0,39}$")

VALID_FILESYSTEMS = frozenset({"ext4", "xfs", "vfat"})
VALID_PARTITION_TABLES = frozenset({"gpt", "msdos"})

# SSH tool validation patterns
PACKAGE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.+\-]{0,127}$")
SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-@]{0,127}$")
REMOTE_FILE_PATH_RE = re.compile(r"^/[a-zA-Z0-9_./\-]+$")

VALID_SERVICE_ACTIONS = frozenset({"start", "stop", "restart", "reload", "enable", "disable", "status"})
VALID_SCRIPT_INTERPRETERS = frozenset({"bash", "sh", "python3", "python", "perl"})


def check_shell_injection(value: str, param_name: str) -> None:
    """Reject any value containing shell metacharacters."""
    if SHELL_METACHAR_RE.search(value):
        raise InvalidParameterError(
            f"Parameter '{param_name}' contains forbidden characters. "
            f"Shell metacharacters are not allowed."
        )


def validate_device_path(device: str, *, allow_partition: bool = False) -> None:
    """Validate a block device path.

    Args:
        device: Device path like /dev/sdb or /dev/sdb1.
        allow_partition: If True, allow partition suffixes (e.g., /dev/sdb1).
    """
    check_shell_injection(device, "device")
    pattern = PARTITION_PATH_RE if allow_partition else DEVICE_PATH_RE
    if not pattern.match(device):
        if allow_partition:
            raise InvalidParameterError(
                f"Device path '{device}' is invalid. "
                f"Must match /dev/[name] or /dev/[name][number] (e.g., /dev/sdb, /dev/sdb1)."
            )
        raise InvalidParameterError(
            f"Device path '{device}' is invalid. "
            f"Must be a whole disk like /dev/sdb (no partition numbers)."
        )


def validate_mount_path(path: str) -> None:
    """Validate a mount point path is safe."""
    check_shell_injection(path, "mount_path")

    if ".." in path:
        raise InvalidParameterError(
            f"Mount path '{path}' contains path traversal (..) which is not allowed."
        )

    if not MOUNT_PATH_RE.match(path):
        raise InvalidParameterError(
            f"Mount path '{path}' is invalid. "
            f"Must be under /mnt/, /srv/, or /media/ "
            f"(e.g., /mnt/data, /srv/storage)."
        )

    # Check against critical system paths
    normalized = path.rstrip("/")
    if normalized in CRITICAL_PATHS:
        raise InvalidParameterError(
            f"Mount path '{path}' is a critical system path and cannot be used."
        )


def validate_storage_id(storage_id: str) -> None:
    """Validate a Proxmox storage identifier."""
    check_shell_injection(storage_id, "storage_id")
    if not STORAGE_ID_RE.match(storage_id):
        raise InvalidParameterError(
            f"Storage ID '{storage_id}' is invalid. "
            f"Must start with a letter, contain only alphanumeric/hyphens/underscores, "
            f"and be at most 64 characters."
        )


def validate_label(label: str) -> None:
    """Validate a filesystem label."""
    check_shell_injection(label, "label")
    if not LABEL_RE.match(label):
        raise InvalidParameterError(
            f"Label '{label}' is invalid. "
            f"Must be alphanumeric with hyphens/underscores, max 16 characters."
        )


def validate_mount_options(options: str) -> None:
    """Validate mount options against the allowlist."""
    check_shell_injection(options, "mount_options")
    parts = [opt.strip() for opt in options.split(",") if opt.strip()]

    for opt in parts:
        # Handle commit=N pattern
        if re.match(r"^commit=\d+$", opt):
            continue
        if opt not in ALLOWED_MOUNT_OPTIONS:
            raise InvalidParameterError(
                f"Mount option '{opt}' is not allowed. "
                f"Allowed options: {', '.join(sorted(ALLOWED_MOUNT_OPTIONS))}"
            )


def validate_mkfs_options(options: str) -> None:
    """Validate mkfs options against the allowlist."""
    check_shell_injection(options, "options")
    if not SAFE_OPTION_RE.match(options):
        raise InvalidParameterError(
            "mkfs options contain invalid characters. Only alphanumeric, =, -, . allowed."
        )
    # Split by spaces and check each flag
    tokens = options.split()
    for token in tokens:
        if token.startswith("-"):
            # Extract the flag part (e.g., "-m" from "-m 1")
            flag = re.match(r"^(-[a-zA-Z])", token)
            if not flag or flag.group(1) not in ALLOWED_MKFS_FLAGS:
                raise InvalidParameterError(f"mkfs flag '{token}' is not allowed.")


def validate_filesystem(filesystem: str) -> None:
    """Validate filesystem type."""
    if filesystem not in VALID_FILESYSTEMS:
        raise InvalidParameterError(
            f"Filesystem '{filesystem}' is not supported. "
            f"Supported: {', '.join(sorted(VALID_FILESYSTEMS))}"
        )


def validate_partition_table(table_type: str) -> None:
    """Validate partition table type."""
    if table_type not in VALID_PARTITION_TABLES:
        raise InvalidParameterError(
            f"Partition table type '{table_type}' is not supported. "
            f"Supported: {', '.join(sorted(VALID_PARTITION_TABLES))}"
        )


def validate_snapname(name: str) -> None:
    """Validate snapshot name matches Proxmox requirements."""
    if not SNAPNAME_RE.match(name):
        raise InvalidParameterError(
            f"Invalid snapshot name '{name}'. Must start with a letter, "
            "contain only [a-zA-Z0-9_-.], and be 1-40 characters."
        )


def validate_uuid(uuid_str: str) -> str:
    """Validate a UUID string format. Returns the validated UUID."""
    if not UUID_RE.match(uuid_str):
        raise InvalidParameterError(
            f"Invalid UUID format: {uuid_str!r}. "
            f"Expected format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )
    return uuid_str


def validate_package_name(name: str) -> None:
    """Validate a system package name."""
    check_shell_injection(name, "package")
    if not PACKAGE_NAME_RE.match(name):
        raise InvalidParameterError(
            f"Package name '{name}' is invalid. "
            f"Must start with alphanumeric and contain only [a-zA-Z0-9_.+-]."
        )


def validate_service_name(name: str) -> None:
    """Validate a systemd service name."""
    check_shell_injection(name, "service")
    if not SERVICE_NAME_RE.match(name):
        raise InvalidParameterError(
            f"Service name '{name}' is invalid. "
            f"Must start with alphanumeric and contain only [a-zA-Z0-9_.\\-@]."
        )


def validate_service_action(action: str) -> None:
    """Validate a systemd service action."""
    if action not in VALID_SERVICE_ACTIONS:
        raise InvalidParameterError(
            f"Service action '{action}' is invalid. "
            f"Allowed: {', '.join(sorted(VALID_SERVICE_ACTIONS))}"
        )


def validate_remote_file_path(path: str) -> None:
    """Validate a remote file path for file transfer."""
    check_shell_injection(path, "file_path")
    if ".." in path:
        raise InvalidParameterError(
            f"File path '{path}' contains path traversal (..) which is not allowed."
        )
    if not REMOTE_FILE_PATH_RE.match(path):
        raise InvalidParameterError(
            f"File path '{path}' is invalid. Must be an absolute path with safe characters."
        )


def validate_script_interpreter(interpreter: str) -> None:
    """Validate a script interpreter name."""
    if interpreter not in VALID_SCRIPT_INTERPRETERS:
        raise InvalidParameterError(
            f"Interpreter '{interpreter}' is not allowed. "
            f"Allowed: {', '.join(sorted(VALID_SCRIPT_INTERPRETERS))}"
        )
