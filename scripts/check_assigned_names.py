"""
Check display names for faculty assignments for branch pk=10.
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

branch = Branch.objects.get(pk=10)
print('Branch:', branch)
cas = CourseAllocation.objects.filter(hod_assignment__branch=branch)
for ca in cas:
    print('Course:', ca.course_code)
    fa = FacultyAssignment.objects.filter(course_allocation=ca).order_by('-assigned_on').first()
    if not fa:
        print('  No assignment')
        continue
    fp = fa.faculty
    user = getattr(fp, 'user', None)
    if user:
        name = user.get_full_name() or getattr(user, 'username', None) or getattr(user, 'email', None)
    else:
        if hasattr(fp, 'get_full_name') and hasattr(fp, 'email'):
            name = fp.get_full_name() or getattr(fp, 'username', None) or getattr(fp, 'email', None)
        else:
            name = getattr(fp, 'display_name', None) or str(fp)
    print('  Assigned on:', fa.assigned_on, 'Name:', name)
