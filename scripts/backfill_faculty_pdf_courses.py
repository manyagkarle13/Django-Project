"""
Backfill `FacultySyllabusPDF.course` for existing saved PDFs where course is NULL.
Usage (from repo root):
    type scripts\backfill_faculty_pdf_courses.py | python manage.py shell
This script attempts to resolve course codes from PDF title / filename and then attach
an existing CollegeLevelCourse when possible. It reports summary counts.
"""
from hod.models import FacultySyllabusPDF
from django.apps import apps
import os

CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
SchemeCourse = apps.get_model('hod', 'SchemeCourse')

candidates = FacultySyllabusPDF.objects.filter(course__isnull=True)
print('Found', candidates.count(), 'faculty PDFs with null course.')
fixed = 0
unresolved = []
for p in candidates.order_by('-created_at'):
    code = None
    if p.title and isinstance(p.title, str):
        parts = p.title.split('_')
        if parts:
            code = parts[0]
    if not code and getattr(p, 'pdf_file', None):
        fname = getattr(p.pdf_file, 'name', '') or ''
        fname_parts = os.path.basename(fname).split('_')
        if fname_parts:
            code = fname_parts[0]
    if not code:
        unresolved.append((p.pk, None))
        continue
    # Try CollegeLevelCourse
    course = CollegeLevelCourse.objects.filter(course_code__iexact=code).first()
    if course:
        p.course = course
        p.save()
        fixed += 1
        print('Assigned CollegeLevelCourse for PDF', p.pk, '->', course.course_code)
        continue
    # Try SchemeCourse (if it points to a CollegeLevelCourse)
    sc = SchemeCourse.objects.filter(course_code__iexact=code).first()
    if sc and getattr(sc, 'course', None):
        p.course = sc.course
        p.save()
        fixed += 1
        print('Assigned SchemeCourse.course for PDF', p.pk, '->', sc.course.course_code)
        continue
    unresolved.append((p.pk, code))

print('\nSummary:')
print('  Fixed:', fixed)
print('  Unresolved:', len(unresolved))
if unresolved:
    print('  Examples (pk,code):', unresolved[:10])
print('Done.')
