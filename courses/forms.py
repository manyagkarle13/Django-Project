# courses/forms.py
from django import forms
from .models import Scheme, Subject, Department, Syllabus

class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'short_name']

class SchemeForm(forms.ModelForm):
    class Meta:
        model = Scheme
        fields = ['department', 'scheme_name', 'admitted_year', 'academic_year']

class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = [
            'scheme','semester','sl_no','course_category','course_code','course_title',
            'L','T','P','cie_marks','see_marks','credits','has_lab','has_activity','notes'
        ]

class SyllabusForm(forms.ModelForm):
    class Meta:
        model = Syllabus
        fields = ['course_objective', 'cie_scheme', 'see_scheme', 'notes']
