"""
URL patterns for the web UI.
"""
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from .ui_views import dashboard, execute_submit, execute_view, log_detail, log_list

app_name = 'ui'

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('execute/', execute_view, name='execute'),
    path('execute/submit/', execute_submit, name='execute-submit'),
    path('logs/', log_list, name='log-list'),
    path('logs/<int:pk>/', log_detail, name='log-detail'),
    # Auth
    path('login/', LoginView.as_view(template_name='toolbox/login.html'), name='login'),
    path('logout/', LogoutView.as_view(next_page='/ui/login/'), name='logout'),
]
