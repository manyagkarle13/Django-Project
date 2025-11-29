# academics/admin.py
from django.contrib import admin
from .models import Branch, CollegeLevelCourse, SemesterCredit, Syllabus, Subject, Scheme


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'active')
    list_filter = ('active',)
    search_fields = ('code', 'name')


@admin.register(CollegeLevelCourse)
class CollegeLevelCourseAdmin(admin.ModelAdmin):
    list_display = ('course_code', 'course_title', 'course_category', 'department', 'credits', 'is_deleted')
    list_filter = ('course_category', 'department', 'is_deleted')
    search_fields = ('course_code', 'course_title')
    readonly_fields = ('created_on', 'deleted_at')


@admin.register(SemesterCredit)
class SemesterCreditAdmin(admin.ModelAdmin):
    list_display = ('branch', 'admission_year', 'deleted')
    list_filter = ('branch', 'admission_year', 'deleted')
    search_fields = ('branch__code', 'admission_year')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Syllabus)
class SyllabusAdmin(admin.ModelAdmin):
    list_display = ('course',)
    search_fields = ('course__course_code', 'course__course_title')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'branch', 'credits', 'is_deleted')
    list_filter = ('branch', 'is_deleted')
    search_fields = ('code', 'title')
    readonly_fields = ('created_on',)


@admin.register(Scheme)
class SchemeAdmin(admin.ModelAdmin):
    list_display = ('name', 'branch', 'is_deleted')
    list_filter = ('branch', 'is_deleted')
    search_fields = ('name',)
    readonly_fields = ('created_on',)
