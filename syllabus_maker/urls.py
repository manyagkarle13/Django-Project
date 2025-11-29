"""
URL configuration for syllabus_maker project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='users/login/', permanent=False), name='home'),
    path('users/', include('users.urls')),
    path('academics/', include('academics.urls')),
    path('hod/', include('hod.urls')),
    path('faculty/', include('facultymodule.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
