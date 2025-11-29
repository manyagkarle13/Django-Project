# courses/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import DepartmentForm, SchemeForm, SubjectForm
from .models import Scheme, Subject, Department
from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()

@login_required
def hod_create_scheme(request):
    if request.method == 'POST':
        form = SchemeForm(request.POST)
        if form.is_valid():
            scheme = form.save(commit=False)
            scheme.created_by = request.user
            scheme.save()
            messages.success(request, "Scheme created.")
            return redirect('hod_dashboard')
    else:
        form = SchemeForm()
    return render(request, 'courses/hod_create_scheme.html', {'form': form})

@login_required
def hod_add_subject(request):
    if request.method == 'POST':
        form = SubjectForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Subject added.")
            return redirect('hod_dashboard')
    else:
        form = SubjectForm()
    return render(request, 'courses/hod_add_subject.html', {'form': form})

@login_required
def hod_assign_faculty(request, scheme_id=None):
    # list subjects and allow assign
    if scheme_id:
        scheme = get_object_or_404(Scheme, id=scheme_id)
        subjects = scheme.subjects.all().order_by('semester','sl_no')
    else:
        subjects = Subject.objects.all().order_by('scheme','semester','sl_no')

    faculties = User.objects.filter(is_staff=False)  # or filter by group/role
    if request.method == 'POST':
        # POST expects subject_id and faculty_id pairs (or single assignment)
        for key, value in request.POST.items():
            if key.startswith('assign_'):
                subject_id = int(key.split('_',1)[1])
                subject = Subject.objects.get(id=subject_id)
                if value:
                    faculty = User.objects.filter(id=int(value)).first()
                    subject.assigned_faculty = faculty
                else:
                    subject.assigned_faculty = None
                subject.save()
        messages.success(request, "Assignments updated.")
        return redirect('hod_dashboard')

    return render(request, 'courses/hod_assign_faculty.html', {'subjects': subjects, 'faculties': faculties})
