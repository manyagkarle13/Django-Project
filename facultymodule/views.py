# facultymodule/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.apps import apps
from django.contrib import messages
from django.urls import reverse, NoReverseMatch
from django.http import HttpResponse, HttpResponseForbidden
from hod.models import SchemeCourse, FacultyAssignment, Faculty, CourseAllocation
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


@login_required
def faculty_dashboard(request):
    """Show faculty their assigned courses from FacultyAssignment only."""
    user = request.user

    # Fetch FacultyAssignment records for this faculty (via Faculty profile)
    faculty_assignments = []
    faculty_profile = None
    try:
        faculty_profile = Faculty.objects.get(user=user)
        faculty_assignments = FacultyAssignment.objects.filter(
            faculty=faculty_profile
        ).select_related(
            'course_allocation'
        ).order_by('-assigned_on')
    except Faculty.DoesNotExist:
        logger.info("Faculty profile not found for user %s", user.username)
        faculty_assignments = []

    # Also fetch SchemeCourse rows assigned to this faculty user (for backward compatibility)
    assigned_courses = SchemeCourse.objects.filter(
        faculty=user
    ).select_related(
        'course'
    ).order_by('semester', 'course_code')

    # Group courses by semester for better display
    courses_by_semester = {}
    for course in assigned_courses:
        sem = course.semester
        courses_by_semester.setdefault(sem, []).append(course)

    context = {
        'assigned_courses': assigned_courses,
        'courses_by_semester': courses_by_semester,
        'faculty_assignments': faculty_assignments,
        'faculty_profile': faculty_profile,
    }
    return render(request, 'facultymodule/faculty_dashboard.html', context)


@login_required
def view_course(request, course_id):
    """
    Show details for a SchemeCourse assigned to the logged-in faculty.
    Safe: raises 404 if not assigned to this user.
    """
    user = request.user
    course = get_object_or_404(SchemeCourse, pk=course_id, faculty=user)

    context = {
        'course': course,
    }
    return render(request, 'facultymodule/view_course.html', context)


@login_required
def add_syllabus(request, course_allocation_id):
    """
    Route faculty to create/edit syllabus for a CourseAllocation.
    GET: Renders the syllabus form
    POST: Saves or generates PDF
    """
    user = request.user
    
    # Get the CourseAllocation
    course_alloc = get_object_or_404(CourseAllocation, pk=course_allocation_id)
    
    # Verify faculty is assigned to this course (optional - just log if missing)
    try:
        faculty_profile = Faculty.objects.get(user=user)
        assignment = FacultyAssignment.objects.get(
            faculty=faculty_profile,
            course_allocation=course_alloc
        )
        logger.info(f"Faculty {user.username} confirmed assigned to {course_alloc.course_code}")
    except (Faculty.DoesNotExist, FacultyAssignment.DoesNotExist) as e:
        logger.warning(f"Assignment check failed for {user.username} on {course_alloc.course_code}: {e}")
    
    # Try to get or create a CollegeLevelCourse from the CourseAllocation
    try:
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        Syllabus = apps.get_model('academics', 'Syllabus')
    except LookupError:
        messages.error(request, "Course model unavailable.")
        return redirect('facultymodule:faculty_dashboard')
    
    # Look for existing course or create one
    course = CollegeLevelCourse.objects.filter(
        course_code=course_alloc.course_code
    ).first()
    
    if not course:
        # Create a new CollegeLevelCourse from CourseAllocation
        course = CollegeLevelCourse.objects.create(
            course_code=course_alloc.course_code,
            course_title=course_alloc.course_title,
            course_category=course_alloc.course_category or 'Main',
            teaching_hours_L=course_alloc.teaching_hours_L or 0,
            teaching_hours_T=course_alloc.teaching_hours_T or 0,
            teaching_hours_P=course_alloc.teaching_hours_P or 0,
            cie_marks=50,
            see_marks=50,
            credits=course_alloc.credits or 0,
            department='All Branches',
            added_by=user,
        )
        logger.info(f"Created CollegeLevelCourse {course.course_code}")
    
    # Find or create Syllabus record for this course
    syllabus = Syllabus.objects.filter(course=course).first()
    if not syllabus:
        syllabus = Syllabus.objects.create(
            course=course
        )
        logger.info(f"Created Syllabus for {course.course_code}")
    
    # Handle POST (form submission)
    if request.method == 'POST':
        action = request.POST.get('action', 'save_only')
        
        # Update syllabus with form data
        syllabus.objectives = request.POST.get('objectives', '')
        syllabus.cie_scheme = request.POST.get('cie', '')
        syllabus.see_scheme = request.POST.get('see', '')
        syllabus.save()
        
        if action == 'generate_pdf':
    # Generate PDF using ReportLab and pass the course_allocation so we can save metadata
            return generate_faculty_syllabus_pdf(request, course, syllabus, course_alloc)
        else:
            messages.success(request, "Syllabus saved successfully!")
            return redirect('facultymodule:faculty_dashboard')

    
    # Handle GET (render form)
    context = {
        'course': course,
        'syllabus': syllabus,
        'initial_semester': getattr(course, 'semester', None),
        'semesters': range(1, 9),
    }
    return render(request, 'facultymodule/edit_syllabus.html', context)


@login_required
def edit_syllabus(request, course_id):
    """
    Allow faculty to edit or prepare syllabus for the given assigned SchemeCourse.
    This function tries to use academics.SyllabusSubmission if available:
      - finds an existing submission for this faculty + course (by course code or course FK)
      - if missing, creates a bare submission record (defensive)
      - then attempts to redirect to an "edit" view in academics (if named).
    If academics.SyllabusSubmission isn't present, or redirect is not available,
    render a fallback template that instructs the user (or shows submission id).
    """
    user = request.user
    # ensure the faculty owns this course
    scheme_course = get_object_or_404(SchemeCourse, pk=course_id, faculty=user)

    # Try to get SyllabusSubmission model
    try:
        SyllabusSubmission = apps.get_model('academics', 'SyllabusSubmission')
    except LookupError:
        messages.error(request, "Syllabus submission feature unavailable (academics app missing).")
        return redirect('facultymodule:faculty_dashboard')

    submission = None
    # Try sensible lookups: by course FK, by course_code, and by scheme_course linkage if any
    try:
        # Try course FK match first if SchemeCourse.course exists and SyllabusSubmission has course FK
        if hasattr(scheme_course, 'course') and scheme_course.course:
            submission = SyllabusSubmission.objects.filter(course=scheme_course.course, faculty=user).first()

        # fallback by matching course code fields (if SyllabusSubmission.course is a FK to a course model with course_code)
        if not submission:
            # attempt filtering by related course__course_code or a field 'course_code' on submission
            qs = SyllabusSubmission.objects.all()
            if qs.model._meta.get_field('course').is_relation:
                # try course__course_code
                try:
                    submission = qs.filter(course__course_code=scheme_course.course_code, faculty=user).first()
                except Exception:
                    submission = qs.filter(faculty=user).first()
            else:
                # no relation; attempt to find a submission for this faculty only
                submission = qs.filter(faculty=user).first()
    except Exception:
        submission = None

    # If still no submission, try to create a bare one
    if not submission:
        try:
            # Attempt to create with a course FK if possible
            create_kwargs = {'faculty': user}
            # attach course FK if SyllabusSubmission has a FK named 'course' and scheme_course.course exists
            if hasattr(scheme_course, 'course') and scheme_course.course:
                create_kwargs['course'] = scheme_course.course
            # Some SyllabusSubmission models require status etc. We'll try minimal create.
            submission = SyllabusSubmission.objects.create(**create_kwargs)
            messages.info(request, "A draft syllabus submission was created for you.")
        except Exception as e:
            logger.exception("Could not create SyllabusSubmission: %s", e)
            messages.error(request, "Could not prepare a syllabus submission automatically. Contact admin.")
            return redirect('facultymodule:faculty_dashboard')

    # Try to redirect to a standard academics edit view (if it exists). Replace name if your project uses a different one.
    try:
        edit_url = reverse('academics:edit_syllabus_submission', args=[submission.pk])
        return redirect(edit_url)
    except NoReverseMatch:
        # fallback: if no named URL exists, render a minimal edit page (template should be created)
        context = {'submission': submission, 'scheme_course': scheme_course}
        return render(request, 'facultymodule/edit_syllabus.html', context)


@login_required
def submit_syllabus(request, course_id):
    """
    Mark the submission as submitted/ready (simple endpoint).
    Expects POST. This is intentionally simple and defensive — adapt to your SyllabusSubmission model.
    """
    if request.method != 'POST':
        return HttpResponse(status=405)

    user = request.user
    scheme_course = get_object_or_404(SchemeCourse, pk=course_id, faculty=user)

    try:
        SyllabusSubmission = apps.get_model('academics', 'SyllabusSubmission')
    except LookupError:
        messages.error(request, "Submission feature unavailable.")
        return redirect('facultymodule:faculty_dashboard')

    # find or create the submission as in edit_syllabus
    submission = SyllabusSubmission.objects.filter(faculty=user).first()
    if not submission:
        try:
            submission = SyllabusSubmission.objects.create(faculty=user, course=getattr(scheme_course, 'course', None))
        except Exception as e:
            logger.exception("Could not create submission: %s", e)
            messages.error(request, "Could not create submission.")
            return redirect('facultymodule:faculty_dashboard')

    # Try to set a status field to SUBMITTED if present
    try:
        if hasattr(submission, 'status'):
            submission.status = 'SUBMITTED'
        # set a submitted_on / submitted_at if it exists
        if hasattr(submission, 'submitted_on'):
            submission.submitted_on = timezone.now()
        submission.save()
        messages.success(request, "Syllabus submitted successfully.")
    except Exception as e:
        logger.exception("Error updating submission: %s", e)
        messages.error(request, "Failed to update submission. Please contact admin.")

    return redirect('facultymodule:faculty_dashboard')

def generate_faculty_syllabus_pdf(request, course, syllabus, course_alloc=None):
    """
    Generate a PDF (ReportLab) and also attempt to save a copy into hod.FacultySyllabusPDF.
    Defensive: won't crash if hod model/table is missing fields (e.g. 'title').
    Returns HttpResponse with PDF for download.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from io import BytesIO
    from datetime import datetime
    from django.http import HttpResponse
    from django.core.files.base import ContentFile
    from django.apps import apps
    from django.utils import timezone
    import logging

    logger = logging.getLogger(__name__)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)

    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#123e77'),
        spaceAfter=12,
        alignment=1  # center
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=13,
        textColor=colors.HexColor('#123e77'),
        spaceAfter=8,
        spaceBefore=8,
    )

    elements = []

    # HEADER
    try:
        header_data = [
            [f"<b>{getattr(course, 'course_code', '')}</b>", f"<b>{getattr(course, 'course_title', '')}</b>"],
            [f"Category: {getattr(course, 'course_category', '')}", f"L-T-P: {getattr(course, 'teaching_hours_L', '')}-{getattr(course, 'teaching_hours_T', '')}-{getattr(course, 'teaching_hours_P', '')}"],
            [f"Credits: {getattr(course, 'credits', '')}", f"CIE: {getattr(syllabus, 'cie_scheme', '') or getattr(course, 'cie_marks', '')} | SEE: {getattr(syllabus, 'see_scheme', '') or getattr(course, 'see_marks', '')}"],
        ]
        header_table = Table(header_data, colWidths=[3.5*inch, 3.5*inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f5f8fa')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#123e77')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('BOX', (0,0), (-1,-1), 1, colors.grey),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.3*inch))
    except Exception as e:
        logger.exception("Error building header: %s", e)

    # OBJECTIVES
    try:
        if getattr(syllabus, 'objectives', None):
            elements.append(Paragraph("Course Objectives", heading_style))
            objectives_text = syllabus.objectives.replace('\n', '<br/>')
            elements.append(Paragraph(objectives_text, styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))
    except Exception as e:
        logger.exception("Error adding objectives: %s", e)

    # OUTCOMES
    try:
        if getattr(syllabus, 'outcomes', None):
            elements.append(Paragraph("Course Outcomes (COs)", heading_style))
            cos_list = syllabus.outcomes.split('\n') if syllabus.outcomes else []
            for i, co in enumerate(cos_list, 1):
                if co.strip():
                    elements.append(Paragraph(f"<b>CO {i}:</b> {co.strip()}", styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))
    except Exception as e:
        logger.exception("Error adding outcomes: %s", e)

    # MODULES
    try:
        if getattr(syllabus, 'modules', None):
            elements.append(Paragraph("Module-wise Breakdown", heading_style))
            modules_list = syllabus.modules.split('\n') if syllabus.modules else []
            for i, module in enumerate(modules_list, 1):
                if module.strip():
                    elements.append(Paragraph(f"<b>Module {i}:</b> {module.strip()}", styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))
    except Exception as e:
        logger.exception("Error adding modules: %s", e)

    # BOOKS
    try:
        if getattr(syllabus, 'books', None):
            elements.append(Paragraph("Prescribed Books", heading_style))
            books_list = syllabus.books.split('\n') if syllabus.books else []
            for book in books_list:
                if book.strip():
                    elements.append(Paragraph(f"• {book.strip()}", styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))
    except Exception as e:
        logger.exception("Error adding books: %s", e)

    # E-RESOURCES / MOOCS
    try:
        if getattr(syllabus, 'ebooks', None) or getattr(syllabus, 'moocs', None):
            elements.append(Paragraph("E-Resources", heading_style))
            if getattr(syllabus, 'ebooks', None):
                elements.append(Paragraph("<b>E-Books:</b>", styles['Normal']))
                ebooks_list = syllabus.ebooks.split('\n')
                for ebook in ebooks_list:
                    if ebook.strip():
                        elements.append(Paragraph(f"• {ebook.strip()}", styles['Normal']))
            if getattr(syllabus, 'moocs', None):
                elements.append(Paragraph("<b>MOOCs:</b>", styles['Normal']))
                moocs_list = syllabus.moocs.split('\n')
                for mooc in moocs_list:
                    if mooc.strip():
                        elements.append(Paragraph(f"• {mooc.strip()}", styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))
    except Exception as e:
        logger.exception("Error adding e-resources: %s", e)

    # ASSESSMENT PLAN
    try:
        if getattr(syllabus, 'cie_scheme', None) or getattr(syllabus, 'see_scheme', None):
            elements.append(Paragraph("Assessment Plan", heading_style))
            assessment_data = [['Assessment Method', 'Marks']]
            if getattr(syllabus, 'cie_scheme', None):
                assessment_data.append(['Continuous Internal Evaluation (CIE)', str(syllabus.cie_scheme)])
            if getattr(syllabus, 'see_scheme', None):
                assessment_data.append(['Semester End Examination (SEE)', str(syllabus.see_scheme)])
            assessment_table = Table(assessment_data, colWidths=[4*inch, 2*inch])
            assessment_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8ADBE9')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOX', (0,0), (-1,-1), 1, colors.grey),
            ]))
            elements.append(assessment_table)
            elements.append(Spacer(1, 0.2*inch))
    except Exception as e:
        logger.exception("Error adding assessment plan: %s", e)

    # LAB WORK
    try:
        if getattr(syllabus, 'lab_work', None):
            elements.append(Paragraph("Laboratory Work", heading_style))
            lab_text = syllabus.lab_work.replace('\n', '<br/>')
            elements.append(Paragraph(lab_text, styles['Normal']))
            elements.append(Spacer(1, 0.2*inch))
    except Exception as e:
        logger.exception("Error adding lab work: %s", e)

    # FOOTER
    try:
        elements.append(Spacer(1, 0.3*inch))
        footer_text = f"<i>Generated by Faculty on {datetime.now().strftime('%d-%m-%Y %H:%M')}</i>"
        elements.append(Paragraph(footer_text, styles['Normal']))
    except Exception as e:
        logger.exception("Error adding footer: %s", e)

    # BUILD PDF
    try:
        doc.build(elements)
        buffer.seek(0)
        pdf_bytes = buffer.getvalue()
    except Exception as e:
        logger.exception("Error building PDF: %s", e)
        messages.error(request, "Failed to generate PDF.")
        return redirect('facultymodule:faculty_dashboard')

    # Defensive save to hod.FacultySyllabusPDF (won't write missing columns)
    try:
        FacultySyllabusPDF = None
        try:
            FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
        except LookupError:
            FacultySyllabusPDF = None

        if FacultySyllabusPDF:
            # figure out branch/year/semester
            branch_obj = None
            year_val = None
            sem_val = None

            if course_alloc is not None:
                branch_obj = getattr(course_alloc, 'branch', None)
                year_val = getattr(course_alloc, 'admission_year', None) or getattr(course_alloc, 'year', None)
                sem_val = getattr(course_alloc, 'semester', None)

            try:
                ca = CourseAllocation.objects.filter(course_code=getattr(course, 'course_code', None)).first()
                if ca:
                    branch_obj = branch_obj or getattr(ca, 'branch', None)
                    year_val = year_val or getattr(ca, 'admission_year', None) or getattr(ca, 'year', None)
                    sem_val = sem_val or getattr(ca, 'semester', None)
            except Exception:
                pass

            branch_obj = branch_obj or getattr(course, 'branch', None) or None

            # also accept year/semester from the form if provided (so HOD filters match)
            try:
                posted_year = request.POST.get('year') if request and hasattr(request, 'POST') else None
                posted_sem = request.POST.get('semester') if request and hasattr(request, 'POST') else None
                if posted_year:
                    year_val = posted_year
                if posted_sem:
                    sem_val = posted_sem
            except Exception:
                pass

            filename = f"{getattr(course, 'course_code', 'syllabus')}_{timezone.now().strftime('%Y%m%d%H%M%S')}.pdf"

            # desired kwargs (we will filter to only actual model fields)
            # Ensure approved=False and rejected=False by default so it appears in pending submissions
            desired_kwargs = {
                'branch': branch_obj,
                'year': str(year_val) if year_val is not None else '',
                'semester': str(sem_val) if sem_val is not None else (str(getattr(course, 'semester', '') or '')),
                'created_by': (request.user if hasattr(request, 'user') else None),
                'course': course,  # Ensure course is set so it appears in pending submissions
                'title': getattr(course, 'course_title', '') or getattr(course, 'course_code', 'Syllabus'),
                'approved': False,  # Explicitly set to False so it appears in pending
                'rejected': False,  # Explicitly set to False for new submissions
                # optional nice-to-have fields may be added here if model/table supports them
            }

            # get concrete field names of the hod model
            model_field_names = {f.name for f in FacultySyllabusPDF._meta.get_fields() if getattr(f, 'concrete', False)}

            # only keep kwargs that the model actually defines
            safe_kwargs = {k: v for k, v in desired_kwargs.items() if k in model_field_names}

            # create the DB row
            pdf_row = FacultySyllabusPDF.objects.create(**safe_kwargs)

            # find a sensible filefield name and save the file bytes
            filefield_name = None
            for candidate in ('pdf_file', 'file', 'pdf', 'document'):
                if candidate in model_field_names:
                    filefield_name = candidate
                    break

            if filefield_name:
                getattr(pdf_row, filefield_name).save(filename, ContentFile(pdf_bytes))
                pdf_row.save()

            logger.info("Saved faculty-generated PDF to FacultySyllabusPDF (pk=%s)", getattr(pdf_row, 'pk', 'n/a'))
    except Exception as e:
        # Non-fatal: log error but allow download to continue
        logger.exception("Failed to save faculty PDF (non-fatal): %s", e)

    # Return PDF response for faculty to download
    try:
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{getattr(course, "course_code", "syllabus")}_syllabus.pdf"'
        return response
    except Exception as e:
        logger.exception("Failed to build HTTP response for PDF: %s", e)
        messages.error(request, "Failed to return PDF.")
        return redirect('facultymodule:faculty_dashboard')
