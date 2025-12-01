from django.urls import path
from . import views

app_name = 'hod'

urlpatterns = [
    # Dashboard
    path('dashboard/', views.dashboard_redirect, name='dashboard_redirect'),
    path('dashboard/<int:branch_pk>/', views.dashboard, name='dashboard_self'),
    
    # Semester Schema
    path('select-semester/<int:branch_pk>/', views.select_semester, name='select_semester'),
    path('edit-semester-schema/<int:branch_pk>/<int:year>/<int:sem>/', views.edit_semester_schema, name='edit_semester_schema'),
    
    # Create & Generate Schemes
    path('create-scheme/<int:branch_pk>/<int:year>/<int:semester>/', views.create_scheme, name='create_scheme'),
    path('create-scheme-form/<int:branch_pk>/<int:year>/<int:semester>/', views.create_scheme_form, name='create_scheme_form'),
    path('generate-pdf/<int:branch_pk>/<int:year>/<int:semester>/', views.generate_pdf_view, name='generate_pdf'),
    path('create-scheme-quick/<int:branch_pk>/<int:year>/<int:semester>/', views.create_scheme_quick, name='create_scheme_quick'),
    
    # Manage Schemes
    path('manage-schemes/<int:branch_pk>/', views.manage_schemes, name='manage_schemes'),
    path('view-scheme/<int:scheme_pk>/', views.view_scheme, name='view_scheme'),
    path('download-scheme/<int:scheme_pk>/', views.download_scheme, name='download_scheme'),
    path('edit-scheme/<int:scheme_pk>/', views.edit_scheme, name='edit_scheme'),
    path('trash-scheme/<int:scheme_pk>/', views.trash_scheme, name='trash_scheme'),
    path('restore-scheme/<int:scheme_pk>/', views.restore_scheme, name='restore_scheme'),
    path('permanent-delete-scheme/<int:scheme_pk>/', views.permanent_delete_scheme, name='permanent_delete_scheme'),
    path('regenerate-scheme/<int:scheme_id>/', views.regenerate_scheme, name='regenerate_scheme'),
    
    path('faculty-assignments/detail/<int:hod_assignment_id>/', views.faculty_assignments_detail, name='faculty_assignments_detail_by_hod'),
    path('faculty-assignments/<int:branch_pk>/', views.faculty_assignments_detail, name='faculty_assignment_detail'),
    path('faculty-assignments/<int:assignment_id>/edit/', views.edit_assignment, name='edit_assignment'),
    path('faculty-assignments/<int:assignment_id>/remove/', views.remove_assignment, name='remove_assignment'),
    
    # Activity History
    path('activity-history/', views.activity_history, name='activity_history'),
    path('activity-history/<int:activity_id>/download/', views.download_scheme_pdf, name='download_scheme_pdf'),
    
    # Form handlers
    path('generate-start-pages/<int:branch_pk>/', views.generate_start_pages, name='generate_start_pages'),
    path('generate-full-pdf/<int:branch_pk>/', views.generate_full_pdf, name='generate_full_pdf'),
    
    # Placeholder views (for template linking compatibility)
    path('view-schema/<int:course_pk>/', views.view_schema, name='view_schema'),
    path('edit-schema/<int:course_pk>/', views.edit_schema, name='edit_schema'),
    path('assign-faculty/<int:course_pk>/', views.assign_faculty, name='assign_faculty'),
    path('view-submission/<int:submission_pk>/', views.view_submission, name='view_submission'),
    path('view-submission-pdf/<int:submission_pk>/', views.view_submission_pdf, name='view_submission_pdf'),
    path('approve-syllabus/<int:submission_pk>/', views.approve_syllabus, name='approve_syllabus'),
    
    # Combined Syllabus
    path('create-combined-syllabus/<int:branch_pk>/', views.create_combined_syllabus, name='create_combined_syllabus'),
    path('generate-combined-syllabus/<int:branch_pk>/', views.generate_combined_syllabus, name='generate_combined_syllabus'),
]