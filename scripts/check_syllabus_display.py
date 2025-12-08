import os
import sys
import django

# Ensure project root is on sys.path
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')
django.setup()

from academics.models import CollegeLevelCourse, Syllabus
from hod.models import FacultyAssignment, CourseAllocation
from django.contrib.auth import get_user_model

code = '23MAIS301'
print('Checking course code:', code)

course = CollegeLevelCourse.objects.filter(course_code=code).first()
if course:
    print('Found CollegeLevelCourse:')
    print('  id:', course.id)
    print('  title:', course.course_title)
    print('  L-T-P:', course.teaching_hours_L, course.teaching_hours_T, course.teaching_hours_P)
    print('  credits:', course.credits)
    print('  cie/see:', course.cie_marks, course.see_marks)
else:
    print('No CollegeLevelCourse found for code')

sy = None
if course:
    sy = Syllabus.objects.filter(course=course).first()
    if sy:
        print('Found Syllabus: id=', sy.id)
        print('  objectives:', repr(sy.objectives))
        print('  outcomes:', repr(sy.outcomes[:200]))
        print('  modules:', repr(sy.modules[:200]))
        print('  books:', repr(sy.books[:200]))
    else:
        print('No Syllabus record linked to the CollegeLevelCourse')

# Check CourseAllocation and FacultyAssignment records for the code
ca = CourseAllocation.objects.filter(course_code=code).first()
if ca:
    print('Found CourseAllocation: id=', ca.id, 'title=', ca.course_title)
    fa_qs = FacultyAssignment.objects.filter(course_allocation=ca)
    print('FacultyAssignment count for this allocation:', fa_qs.count())
    for fa in fa_qs:
        user = fa.faculty.user if hasattr(fa.faculty, 'user') else None
        print('  Assigned faculty:', getattr(user, 'email', str(user)))
else:
    print('No CourseAllocation for code')

print('\nDone')
