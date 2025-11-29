# academics/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.apps import apps
from .models import CollegeLevelCourse
from users.models import CustomUser

@receiver(post_save, sender=CollegeLevelCourse)
def propagate_global_course(sender, instance, created, **kwargs):
    """
    When a new GlobalCourse is created by the Dean,
    automatically create the same subject for all HODs' branches.
    """
    if not created:
        return  # Only propagate when a new course is created

    # Resolve Subject model at runtime to avoid import-time issues / unknown symbol errors
    Subject = apps.get_model("academics", "Subject")

    # Get all HODs (adjust based on your user model)
    hods = CustomUser.objects.filter(role__iexact="HOD")

    for hod in hods:
        # Example: each HOD has a department name stored in hod.department
        # Ensure your HOD model has a field like `department`
        department = getattr(hod, "department", None)
        if not department:
            continue

        # Check if a subject with same course code already exists for that department
        existing = Subject.objects.filter(course_code=instance.course_code, department=department)
        if existing.exists():
            continue  # skip duplicates

        # Create the subject for that department
        Subject.objects.create(
            department=department,
            course_category=instance.course_category,
            course_code=instance.course_code,
            course_title=instance.course_title,
            teaching_hours_L=instance.teaching_hours_L,
            teaching_hours_T=instance.teaching_hours_T,
            teaching_hours_P=instance.teaching_hours_P,
            total_hours=(instance.teaching_hours_L + instance.teaching_hours_T + instance.teaching_hours_P),
            cie_marks=instance.cie_marks,
            see_marks=instance.see_marks,
            total_marks=(instance.cie_marks + instance.see_marks),
            credits=instance.credits,
        )

@receiver(post_save, sender=CollegeLevelCourse)
def add_global_course_to_schemes(sender, instance, created, **kwargs):
    if created:
        # Automatically apply to all existing Schemes
        Scheme = apps.get_model("academics", "Scheme")
        for scheme in Scheme.objects.all():
            scheme.courses.add(instance)  # type: ignore
