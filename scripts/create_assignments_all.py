"""
Create CourseAllocation and FacultyAssignment entries for all existing SchemeCourse rows.

This is non-destructive: it uses get_or_create and update_or_create. It links allocations
to the HODAssignment for the course's branch when available; if no HODAssignment exists
for a branch the script will skip allocations for that branch and report them.

Run with project virtualenv Python:
    .\syllabusmaker\Scripts\python.exe scripts\create_assignments_all.py
"""
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')
import django
django.setup()

from academics.models import Branch
from hod.models import HODAssignment, CourseAllocation, FacultyAssignment, SchemeCourse, Faculty
from django.utils import timezone

skipped_branches = set()
created_alloc = 0
created_fa = 0
updated_fa = 0

sc_qs = SchemeCourse.objects.all()
print('Processing', sc_qs.count(), 'SchemeCourse rows')

for sc in sc_qs:
    # determine branch: prefer sc.branch else sc.scheme.branch
    branch = getattr(sc, 'branch', None)
    if not branch:
        scheme = getattr(sc, 'scheme', None)
        branch = getattr(scheme, 'branch', None) if scheme else None

    if not branch:
        # can't allocate without branch information
        continue

    # find HODAssignment for branch
    hod_qs = HODAssignment.objects.filter(branch=branch)
    if not hod_qs.exists():
        skipped_branches.add(branch.pk)
        continue
    hod = hod_qs.first()

    code = sc.course_code
    title = getattr(sc, 'course_title', '') or ''
    defaults = {'course_title': title, 'course_category': getattr(sc, 'category', '') or ''}
    ca, ca_created = CourseAllocation.objects.get_or_create(hod_assignment=hod, course_code=code, defaults=defaults)
    if ca_created:
        created_alloc += 1

    # Create/update FacultyAssignment if SchemeCourse has faculty set
    if getattr(sc, 'faculty', None):
        user = sc.faculty
        faculty_profile, _ = Faculty.objects.get_or_create(user=user)
        fa, fa_created = FacultyAssignment.objects.update_or_create(
            course_allocation=ca,
            defaults={'faculty': faculty_profile, 'assigned_on': timezone.now()}
        )
        if fa_created:
            created_fa += 1
        else:
            updated_fa += 1

print('Done. allocations created:', created_alloc, 'faculty assignments created:', created_fa, 'updated:', updated_fa)
if skipped_branches:
    print('Skipped branches with no HODAssignment:', skipped_branches)
