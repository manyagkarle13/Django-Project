import logging
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from hod.models import Faculty

logger = logging.getLogger(__name__)

class CustomLoginView(LoginView):
    template_name = 'users/login.html'
    
    def get_success_url(self):
        user = self.request.user
        
        # Redirect based on user role
        if hasattr(user, 'hod_assignment') and user.hod_assignment:
            return reverse_lazy('hod:dashboard_self', kwargs={'branch_pk': user.hod_assignment.branch.pk})
        elif user.role == 'faculty':
            return reverse_lazy('facultymodule:faculty_dashboard')
        elif user.role == 'dean':
            return reverse_lazy('academics:dean_dashboard')  # Adjust as needed
        else:
            return reverse_lazy('users:home')
