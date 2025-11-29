from django.db import models
from django.conf import settings
from users.models import CustomUser

User = settings.AUTH_USER_MODEL


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    short_name = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.name


class Scheme(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    scheme_name = models.CharField(max_length=120)
    admitted_year = models.IntegerField()
    academic_year = models.CharField(max_length=20)
    created_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="courses_schemes_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('department', 'scheme_name', 'admitted_year')

    def __str__(self):
        return f"{self.scheme_name} ({self.department.short_name})"


class Subject(models.Model):
    scheme = models.ForeignKey(Scheme, on_delete=models.CASCADE, related_name='subjects')
    semester = models.IntegerField()
    sl_no = models.IntegerField()
    course_category = models.CharField(max_length=50)
    course_code = models.CharField(max_length=50)
    course_title = models.CharField(max_length=300)
    L = models.IntegerField(default=0)
    T = models.IntegerField(default=0)
    P = models.IntegerField(default=0)
    total_hours_week = models.IntegerField(default=0)
    cie_marks = models.IntegerField(default=0)
    see_marks = models.IntegerField(default=0)
    total_marks = models.IntegerField(default=0)
    credits = models.DecimalField(max_digits=4, decimal_places=2)
    has_lab = models.BooleanField(default=False)
    has_activity = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)
    assigned_faculty = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_subjects'
    )

    def save(self, *args, **kwargs):
        self.total_hours_week = int(self.L or 0) + int(self.T or 0) + int(self.P or 0)
        self.total_marks = int(self.cie_marks or 0) + int(self.see_marks or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.course_code} - {self.course_title}"


class Syllabus(models.Model):
    subject = models.OneToOneField(Subject, on_delete=models.CASCADE, related_name='syllabus')
    course_objective = models.TextField(blank=True, null=True)
    cie_scheme = models.TextField(blank=True, null=True)
    see_scheme = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    last_updated = models.DateTimeField(auto_now=True)
    submitted_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="courses_submitted_syllabi"
)
  # FIXED unique name ✅
    

    def __str__(self):
        return f"Syllabus for {self.subject}"


class CourseOutcome(models.Model):
    syllabus = models.ForeignKey(Syllabus, on_delete=models.CASCADE, related_name='cos')
    co_number = models.IntegerField()
    description = models.TextField()
    mapping = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['co_number']

    def __str__(self):
        return f"CO{self.co_number} - {self.syllabus.subject.course_code}"
