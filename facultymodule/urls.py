from django.urls import path
from . import views

app_name = 'facultymodule'

urlpatterns = [
    path('dashboard/', views.faculty_dashboard, name='faculty_dashboard'),
    path('course/<int:course_id>/', views.view_course, name='view_course'),
    path('syllabus/add/<int:course_allocation_id>/', views.add_syllabus, name='add_syllabus'),
    path('syllabus/<int:course_allocation_id>/pdf/', views.view_syllabus_pdf, name='view_syllabus_pdf'),
    path('syllabus/<int:course_allocation_id>/view/', views.view_syllabus, name='view_syllabus'),
    path('course/<int:course_id>/edit/', views.edit_syllabus, name='edit_syllabus'),
    path('course/<int:course_id>/submit/', views.submit_syllabus, name='submit_syllabus'),
]