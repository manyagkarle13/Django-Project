import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')
django.setup()

from academics.models import Syllabus

# Update the 23NYP syllabus with test outcomes
s = Syllabus.objects.filter(course__course_code='23NYP').first()
if s:
    s.outcomes = """Understand basic yoga asanas and their anatomical implications
Apply pranayama techniques for respiratory health and stress management  
Analyze the philosophical aspects of yoga in modern health context"""
    s.save()
    print(f'✓ Updated 23NYP syllabus with outcomes')
    print(f'  Outcomes: {len(str(s.outcomes))} chars')
    print(f'  Preview: {str(s.outcomes)[:100]}...')
else:
    print('✗ Syllabus not found')
