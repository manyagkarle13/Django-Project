from django.urls import path
from . import views

app_name = "academics"

urlpatterns = [
    # Dean dashboard + review
    path("dean/dashboard/", views.dean_dashboard, name="dean_dashboard"),

    # College level courses
    path("dean/course/add/", views.add_college_level_course, name="add_college_level_course"),
    path("dean/course/<int:pk>/edit/", views.edit_college_level_course, name="edit_college_level_course"),

    # Course PDF view / download
    path("dean/course/<int:pk>/view_pdf/", views.view_course_pdf, name="view_course_pdf"),
    path("dean/course/<int:pk>/download_pdf/", views.download_course_pdf, name="download_course_pdf"),

    # Semester credits add / edit / view / download
    path("dean/semester-credits/add/", views.add_semester_credits, name="add_semester_credits"),
    path("dean/semester-credits/<int:pk>/edit/", views.edit_semester_credit, name="edit_semester_credit"),
    path("dean/semester-credits/<int:pk>/view_pdf/", views.view_semester_credits_pdf, name="view_semester_credits_pdf"),
    path("dean/semester-credits/<int:pk>/download_pdf/", views.download_semester_credits_pdf, name="download_semester_credits_pdf"),

    # Generated syllabi listing + add/edit
    path("dean/syllabi/", views.syllabus_list, name="syllabus_list"),
    path("dean/syllabus/add/<int:course_id>/", views.add_syllabus, name="add_syllabus"),
    path("dean/syllabus/<int:course_id>/edit/", views.add_or_edit_syllabus, name="add_or_edit_syllabus"),

    # Syllabus view/download
    path("dean/syllabus/<int:pk>/view_pdf/", views.view_syllabus_pdf, name="view_syllabus_pdf"),
    path("dean/syllabus/<int:pk>/download_pdf/", views.download_syllabus_pdf, name="download_syllabus_pdf"),
    path('review-history/', views.review_history, name='review_history'),

    # Soft delete / restore / permanent delete for Course
    path("dean/course/<int:pk>/delete/", views.delete_course_pdf, name="delete_course_pdf"),
    path("dean/course/<int:pk>/restore/", views.restore_course_pdf, name="restore_course_pdf"),
    path("dean/course/<int:pk>/permanent_delete/", views.permanent_delete_course_pdf, name="permanent_delete_course_pdf"),

    # Soft delete / restore / permanent delete for SemesterCredit
    path("dean/semester-credit/<int:pk>/delete/", views.delete_credit_pdf, name="delete_credit_pdf"),
    path("dean/semester-credit/<int:pk>/restore/", views.restore_credit_pdf, name="restore_credit_pdf"),
    path("dean/semester-credit/<int:pk>/permanent_delete/", views.permanent_delete_credit_pdf, name="permanent_delete_credit_pdf"),

    # Soft delete / restore / permanent delete for Syllabus
    path("dean/syllabus/<int:pk>/delete/", views.delete_syllabus, name="delete_syllabus"),
    path("dean/syllabus/<int:pk>/restore/", views.restore_syllabus, name="restore_syllabus"),
    path("dean/syllabus/<int:pk>/permanent_delete/", views.permanent_delete_syllabus, name="permanent_delete_syllabus"),
    # academics/urls.py
     path("dean/course/<int:pk>/edit/", views.edit_college_level_course, name="edit_college_level_course"),

    # Add this path (in the appropriate urls.py file):
    path('course/<int:course_pk>/latest-syllabus/', views.redirect_to_latest_syllabus_for_course, name='course_latest_syllabus'),
]
