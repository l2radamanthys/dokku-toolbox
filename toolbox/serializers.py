"""
DRF Serializers for Dokku Toolbox.
"""
from django.contrib.auth.models import User
from rest_framework import serializers

from .models import App, Command, ExecutionLog, Server, SSHKey


class SSHKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = SSHKey
        fields = ['id', 'name', 'key_content', 'key_path', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'key_content': {'write_only': True}  # Hide key content in lists/details for safety
        }


class ServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Server
        fields = [
            'id', 'name', 'host', 'ssh_user', 'ssh_port',
            'ssh_key', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AppSerializer(serializers.ModelSerializer):
    server_name = serializers.CharField(source='server.name', read_only=True)

    class Meta:
        model = App
        fields = [
            'id', 'name', 'server', 'server_name',
            'description', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'server_name', 'created_at', 'updated_at']


class CommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Command
        fields = [
            'id', 'name', 'description', 'command',
            'command_type', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ExecutionLogSerializer(serializers.ModelSerializer):
    command_name = serializers.CharField(source='command.name', read_only=True, default=None)
    app_name = serializers.CharField(source='app.name', read_only=True, default=None)
    server_name = serializers.CharField(source='server.name', read_only=True, default=None)
    triggered_by_username = serializers.CharField(
        source='triggered_by.username', read_only=True, default=None
    )

    class Meta:
        model = ExecutionLog
        fields = [
            'id', 'command', 'command_name', 'app', 'app_name',
            'server', 'server_name', 'command_executed',
            'stdout', 'stderr', 'exit_code', 'status',
            'duration_seconds', 'triggered_by', 'triggered_by_username',
            'executed_at',
        ]
        read_only_fields = fields  # Logs are never mutated via API


# ─── Execution request serializers ──────────────────────────────────────────

class ExecuteCommandSerializer(serializers.Serializer):
    """Payload for POST /api/execute/"""
    command_id = serializers.PrimaryKeyRelatedField(
        queryset=Command.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    custom_command = serializers.CharField(required=False, allow_blank=True)
    server_id = serializers.PrimaryKeyRelatedField(queryset=Server.objects.filter(is_active=True))
    app_id = serializers.PrimaryKeyRelatedField(
        queryset=App.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )

    def validate(self, data):
        has_cmd_id = bool(data.get('command_id'))
        has_custom = bool(data.get('custom_command'))
        if has_cmd_id == has_custom:
            raise serializers.ValidationError("Provide either command_id or custom_command, but not both.")
        return data


class ExecuteOnAppsSerializer(serializers.Serializer):
    """Payload for POST /api/execute/multi/ — run one command on many apps."""
    command_id = serializers.PrimaryKeyRelatedField(
        queryset=Command.objects.filter(is_active=True, command_type=Command.TYPE_APP)
    )
    app_ids = serializers.PrimaryKeyRelatedField(
        queryset=App.objects.filter(is_active=True),
        many=True,
    )


# ─── Config management serializers ──────────────────────────────────────────

class AppConfigSerializer(serializers.Serializer):
    """Response serializer for config:show output."""
    app_id = serializers.IntegerField()
    app_name = serializers.CharField()
    server_name = serializers.CharField()
    config = serializers.DictField(child=serializers.CharField())
    raw_output = serializers.CharField()


class SetConfigSerializer(serializers.Serializer):
    """Payload for setting environment variables."""
    app_id = serializers.PrimaryKeyRelatedField(
        queryset=App.objects.filter(is_active=True)
    )
    variables = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        help_text="Dictionary of KEY: VALUE pairs to set.",
    )

    def validate_variables(self, value):
        if not value:
            raise serializers.ValidationError("At least one variable must be provided.")
        for key in value.keys():
            if not key or not all(c.isalnum() or c == '_' for c in key):
                raise serializers.ValidationError(
                    f"Invalid variable name '{key}'. Use letters, digits, and underscores only."
                )
        return value


class UnsetConfigSerializer(serializers.Serializer):
    """Payload for removing environment variables."""
    app_id = serializers.PrimaryKeyRelatedField(
        queryset=App.objects.filter(is_active=True)
    )
    keys = serializers.ListField(
        child=serializers.CharField(),
        help_text="List of variable names to unset.",
    )

    def validate_keys(self, value):
        if not value:
            raise serializers.ValidationError("At least one key must be provided.")
        for key in value:
            if not key or not all(c.isalnum() or c == '_' for c in key):
                raise serializers.ValidationError(
                    f"Invalid variable name '{key}'. Use letters, digits, and underscores only."
                )
        return value
