"""
Import existing PDF files from MEDIA_ROOT/syllabus_pdfs into hod.FacultySyllabusPDF.
Safe: skips files already recorded. Infers year/semester from filename when possible.
Run with project virtualenv Python: .\syllabusmaker\Scripts\python.exe scripts\import_faculty_pdfs.py
"""
import os
import re
import sys
from pathlib import Path

# Ensure DJANGO_SETTINGS_MODULE points to the project's settings
# Ensure project root is on sys.path so Django settings can be imported when
# this script is run from the `scripts/` directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure DJANGO_SETTINGS_MODULE points to the project's settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')

import django
django.setup()

from django.conf import settings
from django.core.files import File
from hod.models import FacultySyllabusPDF
from academics.models import CollegeLevelCourse, Branch

MEDIA_ROOT = getattr(settings, 'MEDIA_ROOT', os.path.join(Path(__file__).resolve().parents[1], 'media'))
SOURCEDIRS = [os.path.join(MEDIA_ROOT, 'syllabus_pdfs')]

created = 0
skipped = 0
errors = 0
candidates = 0

for sourcedir in SOURCEDIRS:
    if not os.path.isdir(sourcedir):
        print(f"Source dir not found, skipping: {sourcedir}")
        continue

    for root, dirs, files in os.walk(sourcedir):
        for fname in files:
            if not fname.lower().endswith('.pdf'):
                continue
            candidates += 1
            abs_path = os.path.join(root, fname)
            # relative path under MEDIA_ROOT
            rel_path = os.path.relpath(abs_path, MEDIA_ROOT).replace('\\', '/')

            # Skip if already exists (check by file name)
            qs = FacultySyllabusPDF.objects.filter(pdf_file=rel_path)
            update_existing = os.environ.get('UPDATE_EXISTING') == '1'
            if qs.exists() and not update_existing:
                skipped += 1
                continue

            # Heuristics to infer course, branch, year and semester from filename
            year = None
            semester = None
            matched_course = None

            # Prefer 4-digit year like 2025
            m_year = re.search(r"20\d{2}", fname)
            if m_year:
                year = m_year.group(0)
            else:
                # Try two-digit year at start (e.g. '23NYP' -> 2023/2025 ambiguous)
                m2 = re.match(r'^(\d{2})', fname)
                if m2:
                    yy = int(m2.group(1))
                    # map to 2000s; if yy <= current year % 100 + 1 assume 2000+yy
                    from datetime import datetime
                    cur_yy = datetime.now().year % 100
                    century = 2000 if yy <= cur_yy + 1 else 1900
                    year = str(century + yy)

            # semester: look for 'sem' or '_S' tokens
            m_sem = re.search(r'[sS]em(?:ester)?[_ -]?([0-9])', fname)
            if not m_sem:
                m_sem = re.search(r'_S([0-9])', fname)
            if m_sem:
                semester = m_sem.group(1)

            # Attempt to match a CollegeLevelCourse code inside filename
            # Build a list of candidate course codes (longest-first to avoid partial matches)
            course_qs = CollegeLevelCourse.objects.filter(is_deleted=False) if hasattr(CollegeLevelCourse, 'is_deleted') else CollegeLevelCourse.objects.all()
            codes = [c.course_code for c in course_qs]
            codes_sorted = sorted(codes, key=lambda s: -len(s))
            fname_lower = fname.lower()
            for code in codes_sorted:
                if not code:
                    continue
                if code.lower() in fname_lower:
                    try:
                        matched_course = course_qs.get(course_code=code)
                        break
                    except Exception:
                        matched_course = None
                        continue

            # If course found, set branch & semester from it when available
            branch_obj = None
            if matched_course:
                branch_obj = matched_course.branch if getattr(matched_course, 'branch', None) else None
                if hasattr(matched_course, 'semester') and matched_course.semester:
                    semester = str(matched_course.semester)

            try:
                if qs.exists():
                    instance = qs.first()
                    # update missing metadata if any
                    changed = False
                    if (not instance.year or instance.year.strip() == '') and year:
                        instance.year = year
                        changed = True
                    if (not instance.semester or instance.semester.strip() == '') and semester:
                        instance.semester = semester
                        changed = True
                    if (not instance.branch) and branch_obj:
                        instance.branch = branch_obj
                        changed = True
                    if (not instance.course) and matched_course:
                        instance.course = matched_course
                        changed = True
                    if changed:
                        instance.save()
                        print(f"Updated metadata for existing: {rel_path} -> pk={instance.pk} (year={instance.year} sem={instance.semester})")
                        created += 1
                    else:
                        skipped += 1
                else:
                    # create empty instance first
                    instance = FacultySyllabusPDF.objects.create(
                        year=year or '',
                        semester=semester or '',
                        branch=branch_obj,
                        course=matched_course,
                    )
                    # assign existing file (do NOT re-upload; set name directly)
                    instance.pdf_file.name = rel_path
                    instance.save()
                    created += 1
                    print(f"Imported: {rel_path} -> pk={instance.pk} (year={year} sem={semester} course={getattr(matched_course,'course_code',None)})")
            except Exception as e:
                errors += 1
                print(f"ERROR importing {rel_path}: {e}")

print("\nSummary:")
print(f"  Candidates scanned: {candidates}")
print(f"  Imported: {created}")
print(f"  Skipped (already present): {skipped}")
print(f"  Errors: {errors}")

if created:
    print("Imported files created in DB. You can now view them in HOD UI as unapproved.")
else:
    print("No new files imported.")
