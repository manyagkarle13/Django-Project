# courses/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('hod/scheme/create/', views.hod_create_scheme, name='hod_create_scheme'),
    path('hod/subject/add/', views.hod_add_subject, name='hod_add_subject'),
    path('hod/assign/', views.hod_assign_faculty, name='hod_assign_faculty'),
]
