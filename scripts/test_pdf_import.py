import os
import sys
import traceback

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')

try:
    import django
    django.setup()
except Exception as e:
    print('DJANGO_SETUP_FAILED:', e)
    traceback.print_exc()
    sys.exit(2)

print('Django setup OK')

# 1) Try import from hod.pdf_generator
try:
    from hod.pdf_generator import generate_syllabus_pdf_buffer
    print('IMPORT_OK: hod.pdf_generator.generate_syllabus_pdf_buffer')
except Exception as e:
    print('IMPORT_FAILED: hod.pdf_generator ->', e)
    traceback.print_exc()

# 2) Try import from hod.views
try:
    from hod import views as hod_views
    if hasattr(hod_views, 'generate_syllabus_pdf_buffer'):
        print('FOUND: hod.views.generate_syllabus_pdf_buffer')
    else:
        print('NOT_FOUND: hod.views.generate_syllabus_pdf_buffer')
except Exception as e:
    print('IMPORT_FAILED: hod.views ->', e)
    traceback.print_exc()

# 3) If we have a generator by name in globals, try to call it with a sample Syllabus
from django.apps import apps
Syllabus = None
try:
    Syllabus = apps.get_model('academics', 'Syllabus')
except Exception as e:
    print('GET_MODEL_FAILED academics.Syllabus ->', e)

s = None
if Syllabus:
    try:
        s = Syllabus.objects.first()
        print('Syllabus instance:', bool(s))
    except Exception as e:
        print('QUERY_FAILED for Syllabus:', e)
        traceback.print_exc()

# attempt to call whichever function we found
candidates = []
try:
    from hod.pdf_generator import generate_syllabus_pdf_buffer as gen1
    candidates.append(('hod.pdf_generator', gen1))
except Exception:
    pass

try:
    from hod import views as hod_views_2
    if hasattr(hod_views_2, 'generate_syllabus_pdf_buffer'):
        candidates.append(('hod.views', hod_views_2.generate_syllabus_pdf_buffer))
except Exception:
    pass

try:
    from academics import views as acad_views
    if hasattr(acad_views, 'generate_syllabus_pdf_buffer'):
        candidates.append(('academics.views', acad_views.generate_syllabus_pdf_buffer))
except Exception:
    pass

# also check this module path if present on sys.path
try:
    import importlib
    mod = importlib.import_module('facultymodule.views')
    if hasattr(mod, 'generate_syllabus_pdf_buffer'):
        candidates.append(('facultymodule.views', mod.generate_syllabus_pdf_buffer))
except Exception:
    pass

if not candidates:
    print('NO_GENERATOR_CANDIDATES_FOUND')
else:
    for name, func in candidates:
        print('Trying candidate:', name)
        if s is None:
            print('No Syllabus instance to call with; skipping call test for', name)
            continue
        try:
            buf = func(s)
            print('CALL_OK for', name, '->', type(buf))
            if hasattr(buf, 'getvalue'):
                print('buffer has getvalue()')
        except Exception as e:
            print('CALL_FAILED for', name, '->', e)
            traceback.print_exc()
