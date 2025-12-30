from hod.models import FacultySyllabusPDF
from academics.models import Branch
from django.db.models import Q
from django.apps import apps
import os

branch = Branch.objects.get(pk=10)
year = '2023'
semester = '3'

pdf_qs = FacultySyllabusPDF.objects.filter(branch=branch)
if year:
    pdf_qs = pdf_qs.filter(Q(year=str(year)) | Q(year__isnull=True) | Q(year=''))
if semester:
    pdf_qs = pdf_qs.filter(Q(semester=str(semester)) | Q(semester__isnull=True) | Q(semester=''))
print('pdf_qs count:', pdf_qs.count())
latest_qs = pdf_qs.select_related('course', 'created_by').order_by('course_id', '-created_at')
latest_map = {}
for p in latest_qs:
    cid = getattr(p, 'course_id', None)
    if not cid:
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
        if code:
            try:
                CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
                resolved = CollegeLevelCourse.objects.filter(course_code__iexact=code).first()
                if resolved:
                    cid = f"course_{resolved.pk}"
                    setattr(p, '_resolved_course', resolved)
                else:
                    try:
                        SchemeCourse = apps.get_model('hod', 'SchemeCourse')
                        sc = SchemeCourse.objects.filter(branch=branch, year=year, semester=semester, course_code__iexact=code).first()
                        if sc:
                            cid = f"scheme_{sc.pk}"
                            setattr(p, '_resolved_course', sc)
                    except Exception:
                        pass
            except Exception:
                pass
    if cid and cid not in latest_map:
        latest_map[cid] = p

print('mapped keys count', len(latest_map))
for k, v in latest_map.items():
    print('key:', k, 'pdf pk:', v.pk, 'title:', v.title, 'course_id:', getattr(v, 'course_id', None), 'resolved:', getattr(v, '_resolved_course', None))
