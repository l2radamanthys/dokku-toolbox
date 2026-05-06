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
from .services import (
    execute_command,
    execute_command_on_apps,
    fetch_app_config,
    set_app_config,
    unset_app_config,
)

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


# ─── App Config Management ───────────────────────────────────────────────────

@login_required
def app_config_view(request):
    """Render the config management page with server/app selectors."""
    servers = Server.objects.filter(is_active=True)
    apps = App.objects.filter(is_active=True).select_related('server')

    context = {
        'servers': servers,
        'apps': apps,
        'apps_json': json.dumps(
            [{'id': a.id, 'name': a.name, 'server_id': a.server_id} for a in apps]
        ),
    }
    return render(request, 'toolbox/app_config.html', context)


@login_required
def app_config_fetch(request):
    """AJAX endpoint: return config for the selected app as JSON."""
    app_id = request.GET.get('app_id')
    if not app_id:
        return JsonResponse({'error': 'app_id is required.'}, status=400)

    app = get_object_or_404(App.objects.select_related('server'), pk=app_id, is_active=True)

    config_result = fetch_app_config(
        app=app,
        triggered_by=request.user if request.user.is_authenticated else None,
    )

    if not config_result.success:
        return JsonResponse({'error': config_result.error}, status=502)

    return JsonResponse({
        'app_id': app.id,
        'app_name': app.name,
        'server_name': app.server.name,
        'config': config_result.config,
        'raw_output': config_result.raw_output,
    })


@login_required
@require_POST
def app_config_submit(request):
    """Handle config modifications from the UI form."""
    app_id = request.POST.get('app_id')
    action = request.POST.get('action', 'set')

    if not app_id:
        messages.error(request, 'App is required.')
        return redirect('ui:app-config')

    app = get_object_or_404(App.objects.select_related('server'), pk=app_id, is_active=True)

    if action == 'unset':
        # Unset variables
        keys_raw = request.POST.get('unset_keys', '').strip()
        if not keys_raw:
            messages.error(request, 'No variable keys specified for removal.')
            return redirect('ui:app-config')

        keys = [k.strip() for k in keys_raw.split(',') if k.strip()]
        try:
            log = unset_app_config(
                app=app,
                keys=keys,
                triggered_by=request.user,
            )
            if log.status == ExecutionLog.STATUS_SUCCESS:
                messages.success(request, f"Successfully removed {len(keys)} variable(s) from {app.name}.")
            else:
                messages.warning(request, f"Unset completed with status: {log.get_status_display()}")
        except ValueError as exc:
            messages.error(request, str(exc))

    else:
        # Set variables
        var_keys = request.POST.getlist('var_key')
        var_values = request.POST.getlist('var_value')

        if not var_keys:
            messages.error(request, 'No variables provided.')
            return redirect('ui:app-config')

        variables = {}
        for k, v in zip(var_keys, var_values):
            k = k.strip()
            if k:
                variables[k] = v

        if not variables:
            messages.error(request, 'No valid variables to set.')
            return redirect('ui:app-config')

        try:
            log = set_app_config(
                app=app,
                variables=variables,
                triggered_by=request.user,
            )
            if log.status == ExecutionLog.STATUS_SUCCESS:
                messages.success(request, f"Successfully set {len(variables)} variable(s) on {app.name}.")
            else:
                messages.warning(request, f"Config set completed with status: {log.get_status_display()}")
        except ValueError as exc:
            messages.error(request, str(exc))

    return redirect('ui:app-config')
