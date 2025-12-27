from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal


# ---------------- BRANCH (department) ----------------
class Branch(models.Model):
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=120)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} — {self.name}"


class CollegeLevelCourse(models.Model):
    department = models.CharField(max_length=100, default="All Branches")
    course_category = models.CharField(max_length=100)
    course_code = models.CharField(max_length=50)
    course_title = models.CharField(max_length=200)
    
    # NEW: semester field (nullable for safe migration)
    semester = models.PositiveSmallIntegerField(
        null=True, 
        blank=True, 
        help_text="Semester number (1-8). Optional."
    )
    # Admission year for which the dean course applies (e.g., 2023, 2024). Optional.
    admission_year = models.CharField(max_length=8, null=True, blank=True, help_text="Admission year (e.g. 2025). Optional.")
    
    teaching_hours_L = models.IntegerField(default=0)
    teaching_hours_T = models.IntegerField(default=0)
    teaching_hours_P = models.IntegerField(default=0)
    cie_marks = models.IntegerField(default=50)
    see_marks = models.IntegerField(default=50)
    credits = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("0.0"))
    optional_branch = models.CharField(max_length=20, blank=True, null=True)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True)
    syllabus_pdf = models.FileField(upload_to='syllabus_pdfs/', null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_on = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['course_code', 'course_title']

    def __str__(self):
        return f"{self.course_code} - {self.course_title}"


class SemesterCredit(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    admission_year = models.CharField(max_length=20)
    sem1 = models.PositiveIntegerField(null=True, blank=True)
    sem2 = models.PositiveIntegerField(null=True, blank=True)
    sem3 = models.PositiveIntegerField(null=True, blank=True)
    sem4 = models.PositiveIntegerField(null=True, blank=True)
    sem5 = models.PositiveIntegerField(null=True, blank=True)
    sem6 = models.PositiveIntegerField(null=True, blank=True)
    sem7 = models.PositiveIntegerField(null=True, blank=True)
    sem8 = models.PositiveIntegerField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)  # ⚠️ This uses 'deleted' not 'is_deleted'
    # If you want consistency, rename to 'is_deleted'


    def __str__(self):
        return f"{self.branch.code} - {self.admission_year}"


class Syllabus(models.Model):
    course = models.ForeignKey(CollegeLevelCourse, on_delete=models.CASCADE, related_name='syllabi')
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    objectives = models.TextField(blank=True, null=True)
    outcomes = models.TextField(blank=True, null=True)
    outcomes_po_mapping = models.TextField(blank=True, null=True)  # JSON: stores PO mappings for each outcome
    outcomes_pso_mapping = models.TextField(blank=True, null=True)  # JSON: stores PSO mappings for each outcome
    modules = models.TextField(blank=True, null=True)
    modules_topics = models.TextField(blank=True, null=True)  # JSON: stores topics/details for each module
    modules_hours = models.TextField(blank=True, null=True)  # JSON: stores hours for each module
    cie_scheme = models.TextField(blank=True, null=True)
    see_scheme = models.TextField(blank=True, null=True)
    activities = models.TextField(blank=True, null=True)
    lab_work = models.TextField(blank=True, null=True)
    books = models.TextField(blank=True, null=True)
    books_details = models.TextField(blank=True, null=True)  # JSON: stores authors, edition, publisher, year for each book
    reference_books = models.TextField(blank=True, null=True)
    reference_books_details = models.TextField(blank=True, null=True)  # JSON: stores authors, edition, publisher, year for reference books
    ebooks = models.TextField(blank=True, null=True)
    co_matrix = models.TextField(blank=True, null=True)  # JSON: 2D matrix of CO x PO/PSO values
    moocs = models.TextField(blank=True, null=True)
    cie_marks_data = models.TextField(blank=True, null=True)
    assessment_rubrics = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_on']
    
    def __str__(self):
        return f"Syllabus for {self.course.course_code}"


class Subject(models.Model):
    course = models.OneToOneField(CollegeLevelCourse, on_delete=models.CASCADE, related_name='subject')
    code = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=200)
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True)
    credits = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("0.0"))
    created_on = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.title}"


class Scheme(models.Model):
    name = models.CharField(max_length=100)
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='schemes')
    created_on = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.branch.name}"


class SyllabusSubmission(models.Model):
    """Tracks syllabus submission status by faculty."""
    course = models.ForeignKey(
        'CollegeLevelCourse',
        on_delete=models.CASCADE,
        related_name='submissions'
    )
    faculty = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='syllabus_submissions'
    )
    syllabus = models.ForeignKey(
        Syllabus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submissions'
    )
    
    # Status: not_submitted, pending, approved, rejected
    status = models.CharField(
        max_length=20,
        choices=[
            ('not_submitted', 'Not Submitted'),
            ('pending', 'Pending Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        default='not_submitted'
    )
    
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_submissions'
    )
    
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('course', 'faculty')
    
    def __str__(self):
        return f"{self.course.course_code} - {self.faculty.get_full_name()} ({self.status})"

