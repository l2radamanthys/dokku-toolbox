"""
SSH Execution Service
======================
Responsible for all remote SSH communication.

Key design decisions:
- Uses paramiko directly (no subprocess shell) to avoid shell injection.
- Commands are always built by Command.build_remote_command(), never from raw input.
- Connection errors and timeouts are caught and surfaced via ExecutionResult.
- ExecutionLog is written here — callers get back a saved log instance.
- SSH host key policy is configurable; defaults to AutoAddPolicy for ease-of-use,
  but can be set to RejectPolicy for strict production environments.
"""

import logging
import time
from dataclasses import dataclass, field
from io import StringIO
from typing import Optional

import paramiko
from django.conf import settings
from django.contrib.auth.models import User

from .models import App, Command, ExecutionLog, Server

logger = logging.getLogger(__name__)


# ─── Result dataclass ────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """Holds the outcome of a remote command run."""
    stdout: str = ''
    stderr: str = ''
    exit_code: Optional[int] = None
    status: str = ExecutionLog.STATUS_ERROR
    duration_seconds: float = 0.0
    error_message: str = ''


# ─── SSH Client builder ──────────────────────────────────────────────────────

def _build_ssh_client(server: Server) -> paramiko.SSHClient:
    """
    Create and connect a paramiko SSHClient for the given server.
    Raises paramiko exceptions on failure.
    """
    client = paramiko.SSHClient()

    policy_setting = getattr(settings, 'SSH_KNOWN_HOSTS_POLICY', 'auto_add')
    if policy_setting == 'reject':
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    elif policy_setting == 'warn':
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
    else:  # 'auto_add' (default – fine for dev; evaluate for prod)
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {
        'hostname': server.host,
        'port': server.ssh_port,
        'username': server.ssh_user,
        'timeout': getattr(settings, 'SSH_CONNECT_TIMEOUT', 10),
        'allow_agent': True,
        'look_for_keys': True,
    }

    if server.ssh_key:
        if server.ssh_key.key_content:
            # Attempt to load the key content. We try common formats.
            key_io = StringIO(server.ssh_key.key_content.strip())
            pkey = None
            for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]:
                try:
                    pkey = key_class.from_private_key(key_io)
                    break
                except (paramiko.SSHException, ValueError):
                    key_io.seek(0)
            
            if pkey:
                connect_kwargs['pkey'] = pkey
                connect_kwargs['allow_agent'] = False
                connect_kwargs['look_for_keys'] = False
            else:
                logger.error("Could not parse SSH key content for server %s", server.name)
        elif server.ssh_key.key_path:
            connect_kwargs['key_filename'] = server.ssh_key.key_path
            connect_kwargs['allow_agent'] = False
            connect_kwargs['look_for_keys'] = False

    client.connect(**connect_kwargs)
    return client


# ─── Core execution logic ────────────────────────────────────────────────────

def _run_remote(
    client: paramiko.SSHClient,
    remote_command: str,
    timeout: int,
) -> ExecutionResult:
    """
    Execute *remote_command* over an already-open SSH connection.
    Returns an ExecutionResult with stdout/stderr/exit_code populated.
    """
    result = ExecutionResult()
    start = time.monotonic()

    try:
        # get_pty=False: we don't want a pseudo-terminal — cleaner output
        stdin, stdout, stderr = client.exec_command(
            remote_command,
            timeout=timeout,
            get_pty=False,
        )
        stdin.close()

        # Read output fully — safe even for large logs because we set timeout
        result.stdout = stdout.read().decode('utf-8', errors='replace')
        result.stderr = stderr.read().decode('utf-8', errors='replace')
        result.exit_code = stdout.channel.recv_exit_status()
        result.status = (
            ExecutionLog.STATUS_SUCCESS
            if result.exit_code == 0
            else ExecutionLog.STATUS_FAILURE
        )

    except Exception as exc:
        result.status = ExecutionLog.STATUS_ERROR
        result.error_message = str(exc)
        logger.error("SSH exec error for '%s': %s", remote_command, exc)

    finally:
        result.duration_seconds = time.monotonic() - start

    return result


# ─── Public API ──────────────────────────────────────────────────────────────

def execute_command(
    *,
    command: Optional[Command] = None,
    custom_command: Optional[str] = None,
    server: Server,
    app: Optional[App] = None,
    triggered_by: Optional[User] = None,
    skip_validation: bool = False,
) -> ExecutionLog:
    """
    Execute a validated Command or custom string on a Server (optionally scoped to an App).
    """
    # ── Pre-flight validation ────────────────────────────────────────────────
    if not server.is_active:
        raise ValueError(f"Server '{server.name}' is not active.")

    if command:
        if not command.is_active:
            raise ValueError(f"Command '{command.name}' is not active.")

        if command.command_type == Command.TYPE_APP:
            if app is None:
                raise ValueError(f"Command '{command.name}' requires an app.")
            if app.server_id != server.id:
                raise ValueError(f"App '{app.name}' does not belong to server '{server.name}'.")

        if command.command_type == Command.TYPE_GLOBAL and app is not None:
            raise ValueError(f"Command '{command.name}' is global and must not have an app.")

        app_name = app.name if app else None
        remote_cmd = command.build_remote_command(app_name=app_name)
    elif custom_command:
        from .models import validate_safe_command
        # Optional: validate custom command safety
        if not skip_validation:
            validate_safe_command(custom_command)
        if app:
            if app.server_id != server.id:
                raise ValueError(f"App '{app.name}' does not belong to server '{server.name}'.")
            if '{app}' in custom_command:
                remote_cmd = custom_command.replace('{app}', app.name)
            else:
                remote_cmd = f"{app.name} {custom_command}"
        else:
            remote_cmd = custom_command
    else:
        raise ValueError("Must provide either command or custom_command")

    logger.info(
        "Executing on %s: %r (triggered_by=%s)",
        server.host,
        remote_cmd,
        triggered_by,
    )

    # ── Connect & run ────────────────────────────────────────────────────────
    result = ExecutionResult()
    client = None
    try:
        client = _build_ssh_client(server)
        timeout = getattr(settings, 'SSH_COMMAND_TIMEOUT', 60)
        result = _run_remote(client, remote_cmd, timeout=timeout)
    except paramiko.AuthenticationException as exc:
        result.status = ExecutionLog.STATUS_ERROR
        result.error_message = f"Authentication failed: {exc}"
        result.stderr = result.error_message
        logger.error("Auth error connecting to %s: %s", server.host, exc)
    except paramiko.SSHException as exc:
        result.status = ExecutionLog.STATUS_ERROR
        result.error_message = f"SSH error: {exc}"
        result.stderr = result.error_message
        logger.error("SSH error connecting to %s: %s", server.host, exc)
    except OSError as exc:
        result.status = ExecutionLog.STATUS_ERROR
        result.error_message = f"Network error: {exc}"
        result.stderr = result.error_message
        logger.error("Network error connecting to %s: %s", server.host, exc)
    finally:
        if client:
            client.close()

    # ── Persist audit log ────────────────────────────────────────────────────
    log = ExecutionLog.objects.create(
        command=command,
        app=app,
        server=server,
        command_executed=remote_cmd,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        status=result.status,
        duration_seconds=result.duration_seconds,
        triggered_by=triggered_by,
    )

    logger.info(
        "Execution log #%d saved — status=%s exit_code=%s duration=%.2fs",
        log.pk,
        log.status,
        log.exit_code,
        log.duration_seconds or 0,
    )
    return log


def execute_command_on_apps(
    *,
    command: Command,
    apps: list[App],
    triggered_by: Optional[User] = None,
) -> list[ExecutionLog]:
    """
    Execute an app-scoped command across multiple apps (each on its own server).
    Returns a list of ExecutionLog records in the same order as *apps*.
    """
    if command.command_type != Command.TYPE_APP:
        raise ValueError(
            f"execute_command_on_apps requires command_type='app', "
            f"got '{command.command_type}'."
        )

    logs = []
    for app in apps:
        log = execute_command(
            command=command,
            server=app.server,
            app=app,
            triggered_by=triggered_by,
        )
        logs.append(log)
    return logs


# ─── Config management ──────────────────────────────────────────────────────

@dataclass
class ConfigResult:
    """Holds the outcome of a config:show operation."""
    config: dict[str, str] = field(default_factory=dict)
    raw_output: str = ''
    error: str = ''
    success: bool = False


def _parse_config_output(raw: str) -> dict[str, str]:
    """
    Parse the output of `dokku config:show <app>`.
    Format is typically:
        =====> <app> env vars
        KEY:  value
        KEY2: value2
    """
    config = {}
    for line in raw.splitlines():
        # Skip header lines (e.g. "=====> app env vars")
        if line.startswith('=====') or not line.strip():
            continue
        # Split on first colon followed by spaces
        if ':' in line:
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip()
            if key:
                config[key] = value
    return config


def fetch_app_config(
    *,
    app: App,
    triggered_by: Optional[User] = None,
) -> ConfigResult:
    """
    Fetch the environment configuration of a Dokku app via `config:show`.
    Returns a ConfigResult with parsed key-value pairs.
    """
    result = ConfigResult()
    server = app.server

    if not server.is_active:
        result.error = f"Server '{server.name}' is not active."
        return result

    remote_cmd = f"config:show {app.name}"
    logger.info(
        "Fetching config for app '%s' on %s (triggered_by=%s)",
        app.name, server.host, triggered_by,
    )

    client = None
    try:
        client = _build_ssh_client(server)
        timeout = getattr(settings, 'SSH_COMMAND_TIMEOUT', 60)
        exec_result = _run_remote(client, remote_cmd, timeout=timeout)

        result.raw_output = exec_result.stdout
        if exec_result.status == ExecutionLog.STATUS_SUCCESS:
            result.config = _parse_config_output(exec_result.stdout)
            result.success = True
        else:
            result.error = exec_result.stderr or exec_result.error_message or 'Unknown error'

        # Log the execution
        ExecutionLog.objects.create(
            command=None,
            app=app,
            server=server,
            command_executed=remote_cmd,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            exit_code=exec_result.exit_code,
            status=exec_result.status,
            duration_seconds=exec_result.duration_seconds,
            triggered_by=triggered_by,
        )

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        result.error = str(exc)
        logger.error("SSH error fetching config for %s: %s", app.name, exc)
    finally:
        if client:
            client.close()

    return result


def set_app_config(
    *,
    app: App,
    variables: dict[str, str],
    triggered_by: Optional[User] = None,
) -> ExecutionLog:
    """
    Set environment variables on a Dokku app via `config:set`.
    *variables* is a dict of KEY=VALUE pairs to set.
    Returns an ExecutionLog record.
    """
    import shlex
    from .models import validate_safe_command

    server = app.server
    if not server.is_active:
        raise ValueError(f"Server '{server.name}' is not active.")

    if not variables:
        raise ValueError("No variables provided to set.")

    # Build KEY=VALUE pairs — values may contain spaces, so wrap in single quotes
    # inside the SSH command. We validate keys for safety.
    pairs = []
    for key, value in variables.items():
        # Validate key: uppercase letters, digits, underscores only
        if not key or not all(c.isalnum() or c == '_' for c in key):
            raise ValueError(
                f"Invalid variable name '{key}'. "
                "Use uppercase letters, digits, and underscores only."
            )
        pairs.append(f"{key}={shlex.quote(value)}")

    pairs_str = ' '.join(pairs)
    remote_cmd = f"config:set --no-restart {app.name} {pairs_str}"

    # We skip the general validate_safe_command because shlex.quote()
    # makes the values safe, and they might contain characters like ';' 
    # that the general validator rejects.

    logger.info(
        "Setting config for app '%s' on %s: %s (triggered_by=%s)",
        app.name, server.host, pairs_str, triggered_by,
    )

    return execute_command(
        custom_command=remote_cmd,
        server=server,
        triggered_by=triggered_by,
        skip_validation=True,
    )


def unset_app_config(
    *,
    app: App,
    keys: list[str],
    triggered_by: Optional[User] = None,
) -> ExecutionLog:
    """
    Unset (remove) environment variables from a Dokku app via `config:unset`.
    Returns an ExecutionLog record.
    """
    server = app.server
    if not server.is_active:
        raise ValueError(f"Server '{server.name}' is not active.")

    if not keys:
        raise ValueError("No variable keys provided to unset.")

    for key in keys:
        if not key or not all(c.isalnum() or c == '_' for c in key):
            raise ValueError(
                f"Invalid variable name '{key}'. "
                "Use uppercase letters, digits, and underscores only."
            )

    keys_str = ' '.join(keys)
    remote_cmd = f"config:unset --no-restart {app.name} {keys_str}"

    logger.info(
        "Unsetting config keys for app '%s' on %s: %s (triggered_by=%s)",
        app.name, server.host, keys_str, triggered_by,
    )

    return execute_command(
        custom_command=remote_cmd,
        server=server,
        triggered_by=triggered_by,
        skip_validation=True,
    )
