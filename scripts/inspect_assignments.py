"""
Inspect CourseAllocation and FacultyAssignment rows for a given branch/year/semester.
Adjust BRANCH_PK YEAR SEMESTER constants below.
Run with project virtualenv Python.
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
from hod.models import CourseAllocation, FacultyAssignment

BRANCH_PK = 10
YEAR = '2025'
SEMESTER = '3'

branch = Branch.objects.get(pk=BRANCH_PK)
print('Branch:', branch)

# list course allocations for HODAssignment branch
cas = CourseAllocation.objects.filter(hod_assignment__branch=branch)
print('Total CourseAllocation for branch:', cas.count())

for ca in cas:
    print('---')
    print('CourseAllocation id:', ca.pk, 'code:', ca.course_code, 'title:', ca.course_title)
    fas = FacultyAssignment.objects.filter(course_allocation=ca).order_by('-assigned_on')
    print(' FacultyAssignment count:', fas.count())
    for fa in fas:
        print('  FA id:', fa.pk, 'assigned_on:', fa.assigned_on, 'faculty (type):', type(fa.faculty), str(fa.faculty))
        # Try to print linked user if exists
        user = getattr(fa.faculty, 'user', None)
        print('   linked user:', getattr(user, 'id', None), getattr(user, 'email', None) if user else None)
print('Done')
