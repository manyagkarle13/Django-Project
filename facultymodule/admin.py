from django.contrib import admin
from .models import Faculty

@admin.register(Faculty)
class FacultyProxyAdmin(admin.ModelAdmin):
    list_display = ('user', 'department', 'assigned_courses', 'has_uploaded_pdf')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')

    def assigned_courses(self, obj):
        # `assignments` is the related_name on hod.Faculty -> FacultyAssignment
        codes = [fa.course_allocation.course_code for fa in obj.assignments.select_related('course_allocation').all()]
        return ", ".join(codes) if codes else "—"

    assigned_courses.short_description = 'Assigned Courses'

    def has_uploaded_pdf(self, obj):
        # Import here to avoid circular import at module import time
        from hod.models import FacultySyllabusPDF
        return FacultySyllabusPDF.objects.filter(created_by=obj.user, pdf_file__isnull=False).exists()

    has_uploaded_pdf.boolean = True
    has_uploaded_pdf.short_description = 'Uploaded PDF'
