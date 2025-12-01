import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')
django.setup()

from academics.models import Syllabus

# Get the specific syllabus from the screenshot (23NYP)
s = Syllabus.objects.filter(course__course_code='23NYP').first()
if s:
    print(f'✓ Syllabus found for 23NYP')
    print(f'  ID: {s.id}')
    print(f'  Outcomes field exists: {hasattr(s, "outcomes")}')
    print(f'  Outcomes value: {repr(s.outcomes[:150] if s.outcomes else "EMPTY")}')
    print(f'  Outcomes length: {len(str(s.outcomes)) if s.outcomes else 0}')
else:
    print('✗ No syllabus found for 23NYP')

# Check ALL syllabi with outcomes
all_with = Syllabus.objects.filter(outcomes__isnull=False).exclude(outcomes='').count()
print(f'\nTotal syllabi with outcomes: {all_with}')
