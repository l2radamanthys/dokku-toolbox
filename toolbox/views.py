"""
Django REST Framework ViewSets and execution endpoint.
"""
import logging

from django_filters import rest_framework as df_filters
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import App, Command, ExecutionLog, Server
from .serializers import (
    AppSerializer,
    CommandSerializer,
    ExecuteCommandSerializer,
    ExecuteOnAppsSerializer,
    ExecutionLogSerializer,
    ServerSerializer,
)
from .services import execute_command, execute_command_on_apps

logger = logging.getLogger(__name__)


# ─── Filters ─────────────────────────────────────────────────────────────────

class ExecutionLogFilter(df_filters.FilterSet):
    server = df_filters.NumberFilter(field_name='server__id')
    app = df_filters.NumberFilter(field_name='app__id')
    status = df_filters.ChoiceFilter(choices=ExecutionLog.STATUS_CHOICES)
    date_from = df_filters.DateTimeFilter(field_name='executed_at', lookup_expr='gte')
    date_to = df_filters.DateTimeFilter(field_name='executed_at', lookup_expr='lte')

    class Meta:
        model = ExecutionLog
        fields = ['server', 'app', 'status', 'date_from', 'date_to']


# ─── CRUD ViewSets ────────────────────────────────────────────────────────────

class ServerViewSet(viewsets.ModelViewSet):
    queryset = Server.objects.all()
    serializer_class = ServerSerializer
    search_fields = ['name', 'host']
    ordering_fields = ['name', 'created_at']


class AppViewSet(viewsets.ModelViewSet):
    queryset = App.objects.select_related('server').all()
    serializer_class = AppSerializer
    filterset_fields = ['server', 'is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']


class CommandViewSet(viewsets.ModelViewSet):
    queryset = Command.objects.all()
    serializer_class = CommandSerializer
    filterset_fields = ['command_type', 'is_active']
    search_fields = ['name', 'description', 'command']
    ordering_fields = ['name', 'command_type', 'created_at']


class ExecutionLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only — logs are created only by the execution service."""
    queryset = ExecutionLog.objects.select_related(
        'command', 'app', 'server', 'triggered_by'
    ).all()
    serializer_class = ExecutionLogSerializer
    filterset_class = ExecutionLogFilter
    search_fields = ['command_executed', 'stdout', 'stderr']
    ordering_fields = ['executed_at', 'status', 'duration_seconds']


# ─── Execution endpoints ──────────────────────────────────────────────────────

class ExecuteCommandView(APIView):
    """
    POST /api/execute/
    Execute a single validated command on a server (optionally scoped to an app).
    """

    def post(self, request: Request) -> Response:
        ser = ExecuteCommandSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        command: Command | None = ser.validated_data.get('command_id')
        custom_command: str = ser.validated_data.get('custom_command', '')
        server: Server = ser.validated_data['server_id']
        app: App | None = ser.validated_data.get('app_id')

        try:
            log = execute_command(
                command=command,
                custom_command=custom_command,
                server=server,
                app=app,
                triggered_by=request.user if request.user.is_authenticated else None,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("Unexpected error during execute_command: %s", exc)
            return Response(
                {'detail': 'Unexpected server error. Check logs.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            ExecutionLogSerializer(log).data,
            status=status.HTTP_201_CREATED,
        )


class ExecuteOnAppsView(APIView):
    """
    POST /api/execute/multi/
    Execute one app-scoped command on multiple apps at once.
    Returns a list of execution logs.
    """

    def post(self, request: Request) -> Response:
        ser = ExecuteOnAppsSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        command: Command = ser.validated_data['command_id']
        apps: list[App] = ser.validated_data['app_ids']

        try:
            logs = execute_command_on_apps(
                command=command,
                apps=apps,
                triggered_by=request.user if request.user.is_authenticated else None,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("Unexpected error during execute_command_on_apps: %s", exc)
            return Response(
                {'detail': 'Unexpected server error. Check logs.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            ExecutionLogSerializer(logs, many=True).data,
            status=status.HTTP_201_CREATED,
        )
