"""
Web UI views — Django template-based.
"""
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import App, Command, ExecutionLog, Server
from .serializers import ExecutionLogSerializer
from .services import execute_command, execute_command_on_apps

logger = logging.getLogger(__name__)


# ─── Dashboard ────────────────────────────────────────────────────────────────

@login_required
def dashboard(request):
    context = {
        'server_count': Server.objects.filter(is_active=True).count(),
        'app_count': App.objects.filter(is_active=True).count(),
        'command_count': Command.objects.filter(is_active=True).count(),
        'recent_logs': ExecutionLog.objects.select_related(
            'command', 'app', 'server'
        )[:10],
        'success_count': ExecutionLog.objects.filter(status=ExecutionLog.STATUS_SUCCESS).count(),
        'failure_count': ExecutionLog.objects.filter(status=ExecutionLog.STATUS_FAILURE).count(),
        'error_count': ExecutionLog.objects.filter(status=ExecutionLog.STATUS_ERROR).count(),
    }
    return render(request, 'toolbox/dashboard.html', context)


# ─── Execute (UI form) ────────────────────────────────────────────────────────

@login_required
def execute_view(request):
    servers = Server.objects.filter(is_active=True)
    commands = Command.objects.filter(is_active=True).order_by('command_type', 'name')
    apps = App.objects.filter(is_active=True).select_related('server')

    context = {
        'servers': servers,
        'commands': commands,
        'apps': apps,
        'apps_json': json.dumps(
            [{'id': a.id, 'name': a.name, 'server_id': a.server_id} for a in apps]
        ),
        'commands_json': json.dumps(
            [{'id': c.id, 'type': c.command_type} for c in commands]
        ),
    }
    return render(request, 'toolbox/execute.html', context)


@login_required
@require_POST
def execute_submit(request):
    command_id = request.POST.get('command_id')
    custom_command = request.POST.get('custom_command', '').strip()
    server_id = request.POST.get('server_id')
    app_id = request.POST.get('app_id') or None

    # Basic presence check
    if not server_id:
        messages.error(request, 'Server is required.')
        return redirect('ui:execute')

    if not command_id and not custom_command:
        messages.error(request, 'You must provide a command template or a custom command.')
        return redirect('ui:execute')

    command = get_object_or_404(Command, pk=command_id, is_active=True) if command_id else None
    server = get_object_or_404(Server, pk=server_id, is_active=True)
    app = get_object_or_404(App, pk=app_id, is_active=True) if app_id else None

    try:
        log = execute_command(
            command=command,
            custom_command=custom_command if custom_command else None,
            server=server,
            app=app,
            triggered_by=request.user,
        )
        level = messages.SUCCESS if log.status == ExecutionLog.STATUS_SUCCESS else messages.WARNING
        messages.add_message(
            request, level,
            f"Execution completed with status: {log.get_status_display()}"
        )
        return redirect('ui:log-detail', pk=log.pk)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('ui:execute')


# ─── Logs ────────────────────────────────────────────────────────────────────

@login_required
def log_list(request):
    qs = ExecutionLog.objects.select_related('command', 'app', 'server')

    # Filters
    server_id = request.GET.get('server')
    app_id = request.GET.get('app')
    status_filter = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if server_id:
        qs = qs.filter(server_id=server_id)
    if app_id:
        qs = qs.filter(app_id=app_id)
    if status_filter:
        qs = qs.filter(status=status_filter)
    if date_from:
        qs = qs.filter(executed_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(executed_at__date__lte=date_to)

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'page': page,
        'servers': Server.objects.all(),
        'apps': App.objects.select_related('server').all(),
        'status_choices': ExecutionLog.STATUS_CHOICES,
        'filters': {
            'server': server_id,
            'app': app_id,
            'status': status_filter,
            'date_from': date_from,
            'date_to': date_to,
        },
    }
    return render(request, 'toolbox/log_list.html', context)


@login_required
def log_detail(request, pk):
    log = get_object_or_404(
        ExecutionLog.objects.select_related('command', 'app', 'server', 'triggered_by'),
        pk=pk,
    )
    return render(request, 'toolbox/log_detail.html', {'log': log})
