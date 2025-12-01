from django.db import models
from django.conf import settings
from django.utils import timezone
from academics.models import Branch, CollegeLevelCourse
from decimal import Decimal


class ActivityLog(models.Model):
    """Log all HOD activities."""
    ACTION_CHOICES = [
        ('CREATE', 'Created'),
        ('EDIT', 'Edited'),
        ('DELETE', 'Deleted'),
        ('VIEW', 'Viewed'),
        ('DOWNLOAD', 'Downloaded'),
        ('APPROVE', 'Approved'),
        ('REJECT', 'Rejected'),
    ]
    
    hod_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hod_activities'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    content_type = models.CharField(max_length=100)  # 'Course', 'Scheme', 'Syllabus'
    object_id = models.IntegerField()
    object_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    pdf_file = models.FileField(upload_to='hod/activity_pdfs/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.hod_user.email} - {self.action} - {self.object_name}"


class HODAssignment(models.Model):
    """Link HOD user to their branch."""
    hod_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='hod_assignment'
    )
    branch = models.OneToOneField(Branch, on_delete=models.CASCADE, related_name='hod')
    assigned_on = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.hod_user.email} - {self.branch.name}"

    class Meta:
        verbose_name = "HOD Assignment"
        verbose_name_plural = "HOD Assignments"


class CourseAllocation(models.Model):
    """HOD creates/allocates courses to their branch."""
    hod_assignment = models.ForeignKey(
        HODAssignment,
        on_delete=models.CASCADE,
        related_name='course_allocations'
    )
    course_code = models.CharField(max_length=50, unique=True)
    course_title = models.CharField(max_length=200)
    course_category = models.CharField(max_length=100)
    
    teaching_hours_L = models.IntegerField(default=0)
    teaching_hours_T = models.IntegerField(default=0)
    teaching_hours_P = models.IntegerField(default=0)
    credits = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("0.0"))
    
    cie_marks = models.IntegerField(default=50)
    see_marks = models.IntegerField(default=50)
    
    description = models.TextField(blank=True, null=True)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('hod_assignment', 'course_code')
        ordering = ['-created_on']

    def __str__(self):
        return f"{self.course_code} - {self.course_title}"


class CourseScheme(models.Model):
    """Scheme/Curriculum details for a course (HOD enters this)."""
    course_allocation = models.OneToOneField(
        CourseAllocation,
        on_delete=models.CASCADE,
        related_name='scheme'
    )
    
    prerequisites = models.TextField(blank=True, null=True)
    learning_objectives = models.TextField(blank=True, null=True)
    course_outcomes = models.TextField(blank=True, null=True)
    modules = models.TextField(blank=True, null=True)
    cie_details = models.TextField(blank=True, null=True)
    see_details = models.TextField(blank=True, null=True)
    textbooks = models.TextField(blank=True, null=True)
    reference_books = models.TextField(blank=True, null=True)
    online_resources = models.TextField(blank=True, null=True)
    
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Scheme for {self.course_allocation.course_code}"


class Faculty(models.Model):
    """Faculty profile linked to user."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='faculty_profile'
    )
    department = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name()} - Faculty"


class FacultyAssignment(models.Model):
    """Assign faculty to courses."""
    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.CASCADE,
        related_name='assignments'
    )
    course_allocation = models.ForeignKey(
        CourseAllocation,
        on_delete=models.CASCADE
    )
    assigned_on = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.faculty.user.email} - {self.course_allocation.course_code}"


class SchemeCourse(models.Model):
    """HOD-created scheme course rows for a specific branch, year, and semester."""
    scheme = models.ForeignKey('academics.Scheme', on_delete=models.CASCADE, related_name='courses', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, null=True, blank=True, related_name='scheme_courses')
    year = models.IntegerField(null=True, blank=True, help_text="Admission year")
    semester = models.IntegerField()
    course_code = models.CharField(max_length=50)
    course_title = models.CharField(max_length=255, blank=True, null=True)
    course = models.ForeignKey(CollegeLevelCourse, on_delete=models.CASCADE, null=True, blank=True)
    faculty = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_courses')
    
    # Course details
    category = models.CharField(max_length=50, blank=True, null=True, help_text="BSC, ESC, PCC, PEC, OEC, etc.")
    is_elective = models.BooleanField(default=False)
    l = models.IntegerField(default=0, help_text="Lecture hours")
    t = models.IntegerField(default=0, help_text="Tutorial hours")
    p = models.IntegerField(default=0, help_text="Practical hours")
    total_hours = models.IntegerField(default=0, blank=True, null=True)
    cie = models.IntegerField(default=0, help_text="CIE marks")
    see = models.IntegerField(default=0, help_text="SEE marks")
    total_marks = models.IntegerField(default=0, blank=True, null=True)
    credits = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("0.0"), blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('branch', 'year', 'semester', 'course_code')
        indexes = [
            models.Index(fields=['branch', 'year', 'semester']),
            models.Index(fields=['is_elective', 'category']),
        ]
    
    def __str__(self):
        faculty_name = self.faculty.get_full_name() if self.faculty else "Unassigned"
        return f"{self.course_code} - {faculty_name}"


class SchemeDocument(models.Model):
    """Store generated scheme PDFs for easy retrieval and history."""
    branch = models.ForeignKey('academics.Branch', on_delete=models.SET_NULL, null=True, blank=True)
    branch_name = models.CharField(max_length=255, blank=True)
    year = models.IntegerField()
    semester = models.IntegerField()
    title = models.CharField(max_length=255, default='Scheme PDF')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    pdf_file = models.FileField(upload_to='hod/schemes/%Y/%m/%d/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ('branch', 'year', 'semester', 'created_at')

    def __str__(self):
        return f"{self.branch_name} {self.year} Sem{self.semester}"


# ---------------------------------------------------------------------------
# FacultySyllabusPDF
# replaces the broken/duplicate definition; safe, single model for faculty PDFs
# ---------------------------------------------------------------------------
class FacultySyllabusPDF(models.Model):
    """
    Store faculty-generated syllabus PDFs for a branch / year / semester.
    Year and semester are CharFields for flexibility; change to IntegerField if you prefer.
    """
    branch = models.ForeignKey(
        'academics.Branch',            # string to avoid import-order problems
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='faculty_generated_pdfs'
    )

    year = models.CharField(max_length=10, null=True, blank=True)      # e.g. "2025"
    semester = models.CharField(max_length=6, null=True, blank=True)   # e.g. "3"

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='faculty_generated_pdfs'
    )

    pdf_file = models.FileField(upload_to='faculty/syllabi/%Y/%m/%d/', null=True, blank=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    course = models.ForeignKey('academics.CollegeLevelCourse', on_delete=models.SET_NULL, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # approval workflow fields (HOD)
    approved = models.BooleanField(default=False)
    rejected = models.BooleanField(default=False, help_text="Marked as rejected by HOD")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name='approved_faculty_pdfs', on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name='rejected_faculty_pdfs', on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        branch_name = self.branch.name if self.branch else "NoBranch"
        return f"{branch_name} | {self.year} Sem{self.semester}"


# ---------------------------------------------------------------------------
# CombinedSyllabus
# new model appended below — stores merged syllabus (scheme + approved faculty PDFs)
# ---------------------------------------------------------------------------
class CombinedSyllabus(models.Model):
    """
    Stores the combined syllabus PDF produced by HOD. This model is intentionally
    non-destructive and references existing SchemeDocument and FacultySyllabusPDF records.
    """
    name = models.CharField(max_length=255, help_text="Human-friendly file name")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to='hod/combined_syllabi/%Y/%m/%d/', null=True, blank=True)

    # metadata to reconstruct what was merged
    branch = models.ForeignKey('academics.Branch', on_delete=models.SET_NULL, null=True, blank=True)
    year = models.CharField(max_length=10, null=True, blank=True)
    semester = models.CharField(max_length=6, null=True, blank=True)

    included_scheme = models.ForeignKey(SchemeDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name='combined_sets')
    included_faculty_pdfs = models.ManyToManyField(FacultySyllabusPDF, blank=True, related_name='included_in_combined')

    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.year} Sem{self.semester})"
