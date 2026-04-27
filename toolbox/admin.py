"""
Django Admin configuration for Dokku Toolbox.
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import App, Command, ExecutionLog, Server


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ['name', 'host', 'ssh_user', 'ssh_port', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'host']
    list_editable = ['is_active']
    fieldsets = [
        (None, {'fields': ['name', 'is_active']}),
        ('SSH Connection', {'fields': ['host', 'ssh_user', 'ssh_port', 'ssh_key_path']}),
    ]


@admin.register(App)
class AppAdmin(admin.ModelAdmin):
    list_display = ['name', 'server', 'is_active', 'created_at']
    list_filter = ['server', 'is_active']
    search_fields = ['name', 'description']
    list_editable = ['is_active']
    autocomplete_fields = ['server']


@admin.register(Command)
class CommandAdmin(admin.ModelAdmin):
    list_display = ['name', 'command_type', 'command', 'is_active', 'created_at']
    list_filter = ['command_type', 'is_active']
    search_fields = ['name', 'description', 'command']
    list_editable = ['is_active']
    fieldsets = [
        (None, {'fields': ['name', 'description', 'is_active']}),
        ('Command', {'fields': ['command_type', 'command']}),
    ]


@admin.register(ExecutionLog)
class ExecutionLogAdmin(admin.ModelAdmin):
    list_display = [
        'executed_at', 'command_label', 'app', 'server',
        'status_badge', 'exit_code', 'duration_display', 'triggered_by',
    ]
    list_filter = ['status', 'server', 'app', 'command']
    search_fields = ['command_executed', 'stdout', 'stderr']
    date_hierarchy = 'executed_at'
    readonly_fields = [
        'command', 'app', 'server', 'command_executed',
        'stdout', 'stderr', 'exit_code', 'status',
        'duration_seconds', 'triggered_by', 'executed_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Command')
    def command_label(self, obj):
        return obj.command.name if obj.command else '—'

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            ExecutionLog.STATUS_SUCCESS: '#22c55e',
            ExecutionLog.STATUS_FAILURE: '#ef4444',
            ExecutionLog.STATUS_ERROR: '#f97316',
        }
        color = colors.get(obj.status, '#94a3b8')
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            color, obj.get_status_display()
        )

    @admin.display(description='Duration')
    def duration_display(self, obj):
        if obj.duration_seconds is not None:
            return f'{obj.duration_seconds:.2f}s'
        return '—'
