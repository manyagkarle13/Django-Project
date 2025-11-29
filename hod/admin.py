from django.contrib import admin
from .models import HODAssignment, CourseAllocation, Faculty, FacultyAssignment, ActivityLog

@admin.register(HODAssignment)
class HODAssignmentAdmin(admin.ModelAdmin):
    list_display = ('hod_user', 'branch', 'assigned_on')
    list_filter = ('branch', 'assigned_on')
    search_fields = ('hod_user__email', 'branch__name')
    readonly_fields = ('assigned_on',)


@admin.register(CourseAllocation)
class CourseAllocationAdmin(admin.ModelAdmin):
    list_display = ('course_code', 'course_title', 'course_category', 'credits')
    list_filter = ('course_category', 'credits')
    search_fields = ('course_code', 'course_title')


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ('id', 'department')
    list_filter = ('department',)
    search_fields = ('department',)


@admin.register(FacultyAssignment)
class FacultyAssignmentAdmin(admin.ModelAdmin):
    list_display = ('faculty', 'course_allocation', 'assigned_on')
    list_filter = ('assigned_on',)
    search_fields = ('faculty__email', 'course_allocation__course_code')
    readonly_fields = ('assigned_on',)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('hod_user', 'action', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('hod_user__email', 'description')
    readonly_fields = ('created_at', 'hod_user')
