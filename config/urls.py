"""
Root URL configuration for Dokku Toolbox.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('toolbox.urls')),
    # Redirect root to the web UI
    path('', RedirectView.as_view(url='/ui/', permanent=False)),
    path('ui/', include('toolbox.ui_urls')),
]

# Customise admin site branding
admin.site.site_header = 'Dokku Toolbox'
admin.site.site_title = 'Dokku Toolbox Admin'
admin.site.index_title = 'Administration'
