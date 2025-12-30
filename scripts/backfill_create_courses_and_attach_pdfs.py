"""
Create missing CollegeLevelCourse rows from SchemeCourse (when sc.course is null) and
attach existing FacultySyllabusPDF objects whose title/filename contain the course code.

Usage (dry-run):
    type scripts\backfill_create_courses_and_attach_pdfs.py | python manage.py shell

Warning: this will create database records; inspect output before running live.
"""
from hod.models import FacultySyllabusPDF
from django.apps import apps
import os

CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
SchemeCourse = apps.get_model('hod', 'SchemeCourse')

candidates = FacultySyllabusPDF.objects.filter(course__isnull=True)
print('Found', candidates.count(), 'faculty PDFs with null course.')
created = 0
attached = 0
skipped = 0
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
        print('Skipping PDF', p.pk, 'no code found')
        skipped += 1
        continue
    sc = SchemeCourse.objects.filter(course_code__iexact=code).first()
    if not sc:
        print('No SchemeCourse for code', code, 'skipping PDF', p.pk)
        skipped += 1
        continue
    # If the scheme course already points to a CollegeLevelCourse, use it
    if getattr(sc, 'course', None):
        p.course = sc.course
        p.save()
        attached += 1
        print('Attached PDF', p.pk, 'to existing CollegeLevelCourse', sc.course.course_code)
        continue
    # Otherwise, create a new CollegeLevelCourse from scheme data
    print('Would create CollegeLevelCourse for scheme', sc.pk, 'code', code, 'title', sc.course_title)
    # The script by default does DRY RUN; to perform changes set PERFORM_CHANGES = True

PERFORM_CHANGES = False
if PERFORM_CHANGES:
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
            continue
        sc = SchemeCourse.objects.filter(course_code__iexact=code).first()
        if not sc:
            continue
        if getattr(sc, 'course', None):
            p.course = sc.course
            p.save()
            attached += 1
            continue
        # Create course
        try:
            new_course = CollegeLevelCourse.objects.create(
                course_code=code,
                course_title=sc.course_title or code,
                course_category=getattr(sc, 'category', '') or 'Main',
                teaching_hours_L=getattr(sc, 'l', 0) or 0,
                teaching_hours_T=getattr(sc, 't', 0) or 0,
                teaching_hours_P=getattr(sc, 'p', 0) or 0,
                cie_marks=getattr(sc, 'cie', 50) or 50,
                see_marks=getattr(sc, 'see', 50) or 50,
                credits=getattr(sc, 'credits', 0) or 0,
                department='All Branches',
            )
            sc.course = new_course
            sc.save()
            created += 1
            # Attach PDFs that match this code
            for p2 in FacultySyllabusPDF.objects.filter(course__isnull=True):
                if p2.title and p2.title.startswith(code):
                    p2.course = new_course
                    p2.save()
                    attached += 1
            print('Created CollegeLevelCourse', new_course.course_code, 'and attached PDFs')
        except Exception as e:
            print('Failed to create course for', code, e)

print('\nDRY RUN complete')
print('Created:', created, 'Attached:', attached, 'Skipped:', skipped)
print('To perform changes, set PERFORM_CHANGES = True in this script and run it again (careful!).')
