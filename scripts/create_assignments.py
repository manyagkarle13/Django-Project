"""
Create CourseAllocation and FacultyAssignment entries for a branch/year/semester
based on existing SchemeCourse rows. Adjust `BRANCH_PK`, `YEAR`, `SEMESTER` below
if you need different values.

Run with project virtualenv Python:
    .\syllabusmaker\Scripts\python.exe scripts\create_assignments.py
"""
from django.conf import settings
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')
import django
django.setup()

from academics.models import Branch
from hod.models import HODAssignment, CourseAllocation, FacultyAssignment, SchemeCourse, Faculty
from django.utils import timezone

BRANCH_PK = 10
YEAR = '2025'
SEMESTER = '3'

branch = Branch.objects.get(pk=BRANCH_PK)
print('Branch:', branch)

hod_qs = HODAssignment.objects.filter(branch=branch)
if not hod_qs.exists():
    print('No HODAssignment found for branch', branch)
    raise SystemExit(1)

hod_assignment = hod_qs.first()
print('Using HODAssignment for', hod_assignment.hod_user)

# Look for SchemeCourse rows either linked via scheme__branch or direct branch field
sc_qs = SchemeCourse.objects.filter(branch=branch, year=YEAR, semester=SEMESTER)
if not sc_qs.exists():
    sc_qs = SchemeCourse.objects.filter(scheme__branch=branch, year=YEAR, semester=SEMESTER)

print('Found SchemeCourse rows:', sc_qs.count())
created_alloc = 0
created_fa = 0
updated_fa = 0

for sc in sc_qs:
    code = sc.course_code
    title = getattr(sc, 'course_title', '') or ''
    defaults = {'course_title': title, 'course_category': getattr(sc, 'category', '') or ''}
    ca, ca_created = CourseAllocation.objects.get_or_create(hod_assignment=hod_assignment, course_code=code, defaults=defaults)
    if ca_created:
        created_alloc += 1
        print('Created CourseAllocation:', code, 'pk', ca.pk)
    else:
        print('Existing CourseAllocation:', code, 'pk', ca.pk)

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
            print('Created FacultyAssignment for', code, '->', faculty_profile)
        else:
            updated_fa += 1
            print('Updated FacultyAssignment for', code, '->', faculty_profile)

print('Summary: CourseAllocations created:', created_alloc, 'FacultyAssignments created:', created_fa, 'updated:', updated_fa)
