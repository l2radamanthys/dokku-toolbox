"""
Dokku Toolbox – Domain Models
=================================
Server  → SSH target (host, user, port)
App     → Dokku application registered on a server
Command → Reusable, validated command template
ExecutionLog → Immutable audit record of every execution

Design decisions:
- Commands are *templates* stored in the DB; arbitrary shell input is rejected.
- ExecutionLog is append-only (no update/delete in admin/API) to preserve audit.
- App names are validated against Dokku's naming rules (lowercase alphanumeric + hyphens).
"""

import re
from django.db import models
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError

# ─── Validators ─────────────────────────────────────────────────────────────

_dokku_name_re = re.compile(r'^[a-z0-9][a-z0-9\-]*$')


def validate_dokku_name(value: str) -> None:
    """Dokku app names: lowercase alphanumeric + hyphens, must start with alnum."""
    if not _dokku_name_re.match(value):
        raise ValidationError(
            f"'{value}' is not a valid Dokku name. "
            "Use lowercase letters, digits, and hyphens only."
        )


def validate_safe_command(value: str) -> None:
    """
    Prevent shell meta-characters that could enable injection.
    Allowed: letters, digits, spaces, hyphens, underscores, dots, colons, at-sign,
             forward slash, equals sign, and percent (for URL-like args).
    Everything else is rejected.
    """
    forbidden = re.compile(r'[;&|`$<>()\\\'"!*?\[\]#~]')
    if forbidden.search(value):
        raise ValidationError(
            "Command contains forbidden characters. "
            "Shell meta-characters are not allowed."
        )


# ─── Models ─────────────────────────────────────────────────────────────────

class Server(models.Model):
    """SSH-reachable Dokku server."""

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Human-readable label (e.g. 'Production VPS').",
    )
    host = models.CharField(
        max_length=253,
        help_text="Hostname or IP address (e.g. 'dokku.example.com').",
    )
    ssh_user = models.CharField(
        max_length=64,
        default='dokku',
        help_text="SSH user. Dokku installations default to 'dokku'.",
    )
    ssh_port = models.PositiveIntegerField(
        default=22,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
    )
    # SSH key path is intentionally optional: falls back to the agent / ~/.ssh/id_rsa
    ssh_key_path = models.CharField(
        max_length=512,
        blank=True,
        help_text=(
            "Absolute path to the private key file on THIS machine. "
            "Leave blank to use the SSH agent or default key."
        ),
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive servers cannot be targeted for new executions.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Server'
        verbose_name_plural = 'Servers'

    def __str__(self) -> str:
        return f"{self.name} ({self.ssh_user}@{self.host}:{self.ssh_port})"


class App(models.Model):
    """A Dokku application deployed on a specific server."""

    name = models.CharField(
        max_length=128,
        validators=[validate_dokku_name],
        help_text="Dokku app name (must match 'dokku apps:list' output).",
    )
    server = models.ForeignKey(
        Server,
        on_delete=models.CASCADE,
        related_name='apps',
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['server', 'name']
        unique_together = [('server', 'name')]
        verbose_name = 'App'
        verbose_name_plural = 'Apps'

    def __str__(self) -> str:
        return f"{self.name} @ {self.server.name}"


class Command(models.Model):
    """
    A validated, reusable Dokku command template.

    type='global' → executed as:  ssh dokku@host "<command>"
    type='app'    → executed as:  ssh dokku@host "<app> <command>"
                    (can be run against one or many apps)
    """

    TYPE_GLOBAL = 'global'
    TYPE_APP = 'app'
    TYPE_CHOICES = [
        (TYPE_GLOBAL, 'Global'),
        (TYPE_APP, 'App-scoped'),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Human-readable label (e.g. 'Restart App', 'Show Logs').",
    )
    description = models.TextField(blank=True)
    command = models.CharField(
        max_length=512,
        validators=[validate_safe_command],
        help_text=(
            "The Dokku subcommand/args (e.g. 'ps:restart', 'config:set {app} KEY=VAL'). "
            "Use '{app}' as a placeholder for the app name. If omitted, the app name is prepended."
        ),
    )
    command_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default=TYPE_APP,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['command_type', 'name']
        verbose_name = 'Command'
        verbose_name_plural = 'Commands'

    def __str__(self) -> str:
        type_label = dict(self.TYPE_CHOICES).get(self.command_type, self.command_type)
        return f"[{type_label}] {self.name}: {self.command}"

    def build_remote_command(self, app_name: str | None = None) -> str:
        """
        Return the full string to pass to the remote SSH session.
        Raises ValueError if app_name is required but missing.
        """
        if self.command_type == self.TYPE_APP:
            if not app_name:
                raise ValueError(f"Command '{self.name}' requires an app name.")
            # Validate app_name one more time at build time
            validate_dokku_name(app_name)
            if '{app}' in self.command:
                return self.command.replace('{app}', app_name)
            return f"{app_name} {self.command}"
        # Global command
        return f"{self.command}"


class ExecutionLog(models.Model):
    """
    Immutable audit record for every SSH execution.
    Never updated after creation — only appended.
    """

    STATUS_SUCCESS = 'success'
    STATUS_FAILURE = 'failure'
    STATUS_ERROR = 'error'      # SSH/connection error before command ran
    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILURE, 'Failure'),
        (STATUS_ERROR, 'Error'),
    ]

    command = models.ForeignKey(
        Command,
        on_delete=models.SET_NULL,
        null=True,
        related_name='executions',
        help_text="Source command template (kept even if template is deleted later).",
    )
    app = models.ForeignKey(
        App,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='executions',
    )
    server = models.ForeignKey(
        Server,
        on_delete=models.SET_NULL,
        null=True,
        related_name='executions',
    )

    # Expanded command string — captured at execution time for auditability
    command_executed = models.TextField(
        help_text="Full command as sent to the SSH session.",
    )
    stdout = models.TextField(blank=True)
    stderr = models.TextField(blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_ERROR,
    )
    executed_at = models.DateTimeField(auto_now_add=True)
    duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Wall-clock execution time in seconds.",
    )

    # Who triggered this (optional — requires auth)
    triggered_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='executions',
    )

    class Meta:
        ordering = ['-executed_at']
        verbose_name = 'Execution Log'
        verbose_name_plural = 'Execution Logs'
        indexes = [
            models.Index(fields=['-executed_at']),
            models.Index(fields=['server', '-executed_at']),
            models.Index(fields=['app', '-executed_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self) -> str:
        return (
            f"[{self.executed_at:%Y-%m-%d %H:%M:%S}] "
            f"{self.command_executed!r} → {self.status}"
        )
