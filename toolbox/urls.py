"""
REST API URL patterns for Dokku Toolbox.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AppConfigView,
    AppViewSet,
    CommandViewSet,
    ExecuteCommandView,
    ExecuteOnAppsView,
    ExecutionLogViewSet,
    ServerViewSet,
    SetAppConfigView,
    UnsetAppConfigView,
)

router = DefaultRouter()
router.register(r'servers', ServerViewSet, basename='server')
router.register(r'apps', AppViewSet, basename='app')
router.register(r'commands', CommandViewSet, basename='command')
router.register(r'logs', ExecutionLogViewSet, basename='executionlog')

urlpatterns = [
    path('', include(router.urls)),
    path('execute/', ExecuteCommandView.as_view(), name='execute'),
    path('execute/multi/', ExecuteOnAppsView.as_view(), name='execute-multi'),
    # Config management
    path('config/<int:app_id>/', AppConfigView.as_view(), name='app-config'),
    path('config/set/', SetAppConfigView.as_view(), name='app-config-set'),
    path('config/unset/', UnsetAppConfigView.as_view(), name='app-config-unset'),
    # DRF browsable API login
    path('auth/', include('rest_framework.urls', namespace='rest_framework')),
]
