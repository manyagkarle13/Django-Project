from hod.models import FacultySyllabusPDF
from academics.models import Branch
from django.apps import apps
import os
branch = Branch.objects.get(pk=10)
for p in FacultySyllabusPDF.objects.filter(branch=branch).order_by('-created_at'):
    if p.title and p.title.startswith('23IS503'):
        code = None
        if p.title and isinstance(p.title, str):
            parts = p.title.split('_')
            if parts:
                code = parts[0]
        if not code and getattr(p,'pdf_file',None):
            fname = getattr(p.pdf_file,'name','') or ''
            fname_parts = os.path.basename(fname).split('_')
            if fname_parts:
                code = fname_parts[0]
        print('PDF', p.pk, 'title', p.title, 'code', code)
        CollegeLevelCourse = apps.get_model('academics','CollegeLevelCourse')
        resolved = CollegeLevelCourse.objects.filter(course_code__iexact=code).first()
        print('  college resolved:', bool(resolved), getattr(resolved,'pk',None))
        SchemeCourse = apps.get_model('hod','SchemeCourse')
        sc = SchemeCourse.objects.filter(branch=branch, year='2023', semester='3', course_code__iexact=code).first()
        print('  scheme resolved:', bool(sc), getattr(sc,'pk',None))
