import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')
django.setup()

from academics.models import Syllabus

s = Syllabus.objects.filter(course__course_code='23NYP').first()
if s:
    s.objectives = 'Students will gain the basic knowledge of data communication and computer networks.'
    s.outcomes = """Explain the Ethernet Standard and Networking devices, Connecting devices and different protocols at the network, transport and application layers.
Apply suitable subnetting and IP addressing for a given Requirement, Switching techniques as per need.
Analyze different protocols at MAC sub-layer, Network and transport layers.
Design networks applying Internetworking concepts and appropriate IP addressing for a given problem"""
    s.save()
    print('✓ Updated 23NYP with reference data')
    print(f'  Objectives: {len(s.objectives)} chars')
    print(f'  Outcomes: {len(s.outcomes)} chars (4 lines)')
else:
    print('✗ Not found')
