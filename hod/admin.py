from django.contrib import admin
from django.utils import timezone

from .models import (
    FacultySyllabusPDF,
    CombinedSyllabus,
    SchemeDocument,
    CourseAllocation,
    FacultyAssignment,
)


@admin.action(description='Mark selected faculty syllabi as approved')
def approve_selected(modeladmin, request, queryset):
    now = timezone.now()
    updated = queryset.update(approved=True, approved_by=request.user, approved_at=now)
    modeladmin.message_user(request, f"Marked {updated} file(s) as approved.")


@admin.action(description='Mark selected faculty syllabi as unapproved')
def unapprove_selected(modeladmin, request, queryset):
    updated = queryset.update(approved=False, approved_by=None, approved_at=None)
    modeladmin.message_user(request, f"Marked {updated} file(s) as unapproved.")


@admin.register(FacultySyllabusPDF)
class FacultySyllabusPDFAdmin(admin.ModelAdmin):
    list_display = ('id', 'pdf_file', 'branch', 'year', 'semester', 'created_by', 'approved', 'approved_by', 'approved_at')
    list_filter = ('approved', 'year', 'semester', 'branch')
    search_fields = ('pdf_file', 'title', 'created_by__email', 'course__course_code')
    actions = (approve_selected, unapprove_selected)


@admin.register(CombinedSyllabus)
class CombinedSyllabusAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'branch', 'year', 'semester', 'created_by', 'created_at')
    search_fields = ('name',)


@admin.register(SchemeDocument)
class SchemeDocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'branch_name', 'year', 'semester', 'title', 'created_by', 'created_at')
    search_fields = ('branch_name', 'title')


@admin.register(CourseAllocation)
class CourseAllocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'course_code', 'course_title', 'hod_assignment')
    search_fields = ('course_code', 'course_title')


@admin.register(FacultyAssignment)
class FacultyAssignmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'faculty', 'course_allocation', 'assigned_on')
    search_fields = ('faculty__user__email', 'course_allocation__course_code')
