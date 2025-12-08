# facultymodule/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.apps import apps
from django.contrib import messages
from django.urls import reverse, NoReverseMatch
from django.http import HttpResponse, HttpResponseForbidden, FileResponse
from hod.models import SchemeCourse, FacultyAssignment, Faculty, CourseAllocation
import logging
import io
import os
from django.conf import settings
from django.utils import timezone
# from viewa.py import generate_syllabus_pdf_buffer as _gen_buf

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

    # Annotate each FacultyAssignment with whether a Syllabus exists for that course_code
    try:
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        Syllabus = apps.get_model('academics', 'Syllabus')
        FacultySyllabusPDF = None
        try:
            FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
        except LookupError:
            FacultySyllabusPDF = None
        for fa in faculty_assignments:
            try:
                code = getattr(fa.course_allocation, 'course_code', None)
                fa._linked_course = CollegeLevelCourse.objects.filter(course_code=code).first()
                fa.has_syllabus = bool(fa._linked_course and Syllabus.objects.filter(course=fa._linked_course).exists())
                # check for existing faculty-generated PDF for this course
                fa.has_pdf = False
                fa.pdf_url = None
                if FacultySyllabusPDF and fa._linked_course:
                    latest_pdf = FacultySyllabusPDF.objects.filter(course=fa._linked_course).order_by('-created_at').first()
                    if latest_pdf and getattr(latest_pdf, 'pdf_file'):
                        fa.has_pdf = True
                        try:
                            fa.pdf_url = latest_pdf.pdf_file.url
                        except Exception:
                            # fallback to a view URL
                            try:
                                fa.pdf_url = reverse('facultymodule:view_syllabus_pdf', args=[fa.course_allocation.id])
                            except Exception:
                                fa.pdf_url = None
            except Exception:
                fa.has_syllabus = False
                fa._linked_course = None
                fa.has_pdf = False
                fa.pdf_url = None
    except LookupError:
        # academics app not available; default to False
        for fa in faculty_assignments:
            fa.has_syllabus = False
            fa._linked_course = None
            fa.has_pdf = False
            fa.pdf_url = None

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
        
        # First, update course (CollegeLevelCourse) with basic editable fields
        from decimal import Decimal
        try:
            # basic text fields
            new_title = request.POST.get('course_title')
            if new_title:
                course.course_title = new_title.strip()
            new_category = request.POST.get('course_category')
            if new_category:
                course.course_category = new_category.strip()

            # teaching hours L/T/P
            try:
                l_val = int(request.POST.get('l') or request.POST.get('id_l') or course.teaching_hours_L or 0)
            except Exception:
                l_val = course.teaching_hours_L or 0
            try:
                t_val = int(request.POST.get('t') or request.POST.get('id_t') or course.teaching_hours_T or 0)
            except Exception:
                t_val = course.teaching_hours_T or 0
            try:
                p_val = int(request.POST.get('p') or request.POST.get('id_p') or course.teaching_hours_P or 0)
            except Exception:
                p_val = course.teaching_hours_P or 0

            course.teaching_hours_L = l_val
            course.teaching_hours_T = t_val
            course.teaching_hours_P = p_val

            # credits
            try:
                cred = request.POST.get('credits')
                if cred is not None and cred != '':
                    course.credits = Decimal(str(cred))
            except Exception:
                pass

            # CIE/SEE marks
            try:
                cie_val = request.POST.get('cie')
                if cie_val is not None and cie_val != '':
                    course.cie_marks = int(cie_val)
            except Exception:
                pass
            try:
                see_val = request.POST.get('see')
                if see_val is not None and see_val != '':
                    course.see_marks = int(see_val)
            except Exception:
                pass

            # semester
            sem = request.POST.get('semester')
            if sem:
                try:
                    course.semester = int(sem)
                except Exception:
                    course.semester = course.semester

            try:
                course.save()
            except Exception:
                logger.exception('Failed to save CollegeLevelCourse updates for %s', getattr(course, 'course_code', 'n/a'))

        except Exception:
            logger.exception('Error updating course from POST data')

        # Update syllabus with form data (parse dynamic fields populated by JS)
        import json

        try:
            syllabus.objectives = request.POST.get('objectives', '').strip()
            syllabus.cie_scheme = request.POST.get('cie', '').strip()
            syllabus.see_scheme = request.POST.get('see', '').strip()

            # ===== Course Outcomes (COs) and mappings =====
            co_items = []
            for k in request.POST.keys():
                if k.startswith('co_') and k[3:].isdigit():
                    try:
                        idx = int(k[3:])
                        co_items.append((idx, request.POST.get(k, '').strip()))
                    except Exception:
                        continue
            co_items.sort(key=lambda x: x[0])
            outcomes_lines = [text for _, text in co_items if text]
            syllabus.outcomes = '\n'.join(outcomes_lines)

            po_mappings = []
            pso_mappings = []
            for idx, _ in co_items:
                po = request.POST.get(f'co_map_po_{idx}', '').strip()
                pso = request.POST.get(f'co_map_pso_{idx}', '').strip()
                po_mappings.append(po)
                pso_mappings.append(pso)

            syllabus.outcomes_po_mapping = json.dumps(po_mappings) if any(po_mappings) else ''
            syllabus.outcomes_pso_mapping = json.dumps(pso_mappings) if any(pso_mappings) else ''

            # ===== Modules (titles, topics, hours) =====
            modules = []
            modules_topics = []
            modules_hours = []
            midx = 1
            while True:
                title = request.POST.get(f'module_title_{midx}')
                if title is None:
                    break
                title = (title or '').strip()
                topics = (request.POST.get(f'module_topics_{midx}', '') or '').strip()
                hours = (request.POST.get(f'module_hours_{midx}', '') or '').strip()
                if title:
                    modules.append(title)
                    modules_topics.append(topics)
                    modules_hours.append(hours)
                midx += 1

            syllabus.modules = '\n'.join(modules)
            syllabus.modules_topics = json.dumps(modules_topics) if any(modules_topics) else ''
            syllabus.modules_hours = json.dumps(modules_hours) if any(modules_hours) else ''

            # ===== Prescribed books =====
            books = []
            books_details = []
            bidx = 1
            while True:
                title = request.POST.get(f'prescribed_title_{bidx}')
                if title is None:
                    break
                title = (title or '').strip()
                if title:
                    books.append(title)
                    detail = {
                        'authors': (request.POST.get(f'prescribed_authors_{bidx}', '') or '').strip(),
                        'edition': (request.POST.get(f'prescribed_edition_{bidx}', '') or '').strip(),
                        'publisher': (request.POST.get(f'prescribed_publisher_{bidx}', '') or '').strip(),
                        'year': (request.POST.get(f'prescribed_year_{bidx}', '') or '').strip(),
                    }
                    books_details.append(detail)
                bidx += 1

            syllabus.books = '\n'.join(books)
            syllabus.books_details = json.dumps(books_details) if books_details else ''

            # ===== Reference books =====
            ref_books = []
            ref_books_details = []
            ridx = 1
            while True:
                title = request.POST.get(f'reference_title_{ridx}')
                if title is None:
                    break
                title = (title or '').strip()
                if title:
                    ref_books.append(title)
                    detail = {
                        'authors': (request.POST.get(f'reference_authors_{ridx}', '') or '').strip(),
                        'edition': (request.POST.get(f'reference_edition_{ridx}', '') or '').strip(),
                        'publisher': (request.POST.get(f'reference_publisher_{ridx}', '') or '').strip(),
                        'year': (request.POST.get(f'reference_year_{ridx}', '') or '').strip(),
                    }
                    ref_books_details.append(detail)
                ridx += 1

            syllabus.reference_books = '\n'.join(ref_books)
            syllabus.reference_books_details = json.dumps(ref_books_details) if ref_books_details else ''

            # ===== Ebooks and MOOCs =====
            ebooks = []
            eidx = 1
            while True:
                ev = request.POST.get(f'ebook_{eidx}')
                if ev is None:
                    break
                if (ev or '').strip():
                    ebooks.append((ev or '').strip())
                eidx += 1
            syllabus.ebooks = '\n'.join(ebooks)

            moocs = []
            mid = 1
            while True:
                mv = request.POST.get(f'mooc_{mid}')
                if mv is None:
                    break
                if (mv or '').strip():
                    moocs.append((mv or '').strip())
                mid += 1
            syllabus.moocs = '\n'.join(moocs)

            # ===== Lab work =====
            lab_lines = []
            lidx = 1
            while True:
                lv = request.POST.get(f'lab_item_{lidx}')
                if lv is None:
                    break
                if (lv or '').strip():
                    lab_lines.append((lv or '').strip())
                lidx += 1
            syllabus.lab_work = '\n'.join(lab_lines)

            # ===== Assessment rows -> cie_marks_data =====
            cie_data = []
            aidx = 1
            while True:
                tool = request.POST.get(f'tool_{aidx}')
                if tool is None:
                    break
                tool = (tool or '').strip()
                remarks = (request.POST.get(f'remarks_{aidx}', '') or '').strip()
                marks = (request.POST.get(f'marks_{aidx}', '') or '').strip()
                if tool or remarks or marks:
                    cie_data.append({'tool': tool, 'remarks': remarks, 'marks': marks})
                aidx += 1
            syllabus.cie_marks_data = json.dumps(cie_data) if cie_data else ''

            # ===== CO Matrix =====
            try:
                outcomes_count = len(outcomes_lines) if outcomes_lines else 0
                if outcomes_count == 0:
                    # fallback to 3 rows if none present
                    outcomes_count = 3
                pos_count = 14  # 12 PO + 2 PSO
                matrix = []
                for i in range(1, outcomes_count + 1):
                    row = []
                    for j in range(1, pos_count + 1):
                        v = request.POST.get(f'matrix_{i}_{j}', '')
                        row.append((v or '').strip())
                    matrix.append(row)
                syllabus.co_matrix = json.dumps(matrix) if matrix else ''
            except Exception:
                syllabus.co_matrix = ''

            # Persist
            syllabus.save()
        except Exception as e:
            logger.exception("Error parsing syllabus POST data: %s", e)
            # fallback: ensure at least minimal save took place
            try:
                syllabus.save()
            except Exception:
                logger.exception("Failed to save syllabus after parse error")
        # After save, attach transient display attributes so the form shows values on redirect GET
        try:
            # hours/week and totals used by the template
            setattr(syllabus, 'hours_week', (course.teaching_hours_L or 0) + (course.teaching_hours_T or 0) + (course.teaching_hours_P or 0))
            setattr(syllabus, 'total_hours', (course.teaching_hours_L or 0) * 9 + (course.teaching_hours_P or 0) * 14)
            setattr(syllabus, 'credits', str(course.credits or ''))
            setattr(syllabus, 'cie', getattr(course, 'cie_marks', ''))
            setattr(syllabus, 'see', getattr(course, 'see_marks', ''))
            setattr(syllabus, 'semester', getattr(course, 'semester', None))
        except Exception:
            pass
        
        if action == 'generate_pdf':
    # Generate PDF using ReportLab and pass the course_allocation so we can save metadata
            return generate_faculty_syllabus_pdf(request, course, syllabus, course_alloc)
        else:
            messages.success(request, "Syllabus saved successfully!")
            return redirect('facultymodule:faculty_dashboard')

    
    # Handle GET (render form)
    # Attach transient display attributes for template fields that live on Course
    try:
        setattr(syllabus, 'l', course.teaching_hours_L or 0)
        setattr(syllabus, 't', course.teaching_hours_T or 0)
        setattr(syllabus, 'p', course.teaching_hours_P or 0)
        setattr(syllabus, 'course_category', getattr(course, 'course_category', '') or '')
        setattr(syllabus, 'hours_week', (course.teaching_hours_L or 0) + (course.teaching_hours_T or 0) + (course.teaching_hours_P or 0))
        setattr(syllabus, 'total_hours', (course.teaching_hours_L or 0) * 9 + (course.teaching_hours_P or 0) * 14)
        setattr(syllabus, 'credits', str(course.credits or ''))
        setattr(syllabus, 'cie', getattr(course, 'cie_marks', ''))
        setattr(syllabus, 'see', getattr(course, 'see_marks', ''))
        setattr(syllabus, 'semester', getattr(course, 'semester', None))
    except Exception:
        pass

    # Prepare module_rows (for template rendering of module table)
    module_rows = []
    prescribed_books = []
    reference_books = []
    ebooks = []
    moocs = []
    try:
        # modules
        modules_list = str(syllabus.modules).split('\n') if syllabus.modules else []
        modules_topics = json.loads(syllabus.modules_topics) if syllabus.modules_topics else []
        modules_hours = json.loads(syllabus.modules_hours) if syllabus.modules_hours else []
        for i, title in enumerate(modules_list, 1):
            module_rows.append({
                'index': i,
                'title': title,
                'topics': modules_topics[i-1] if i-1 < len(modules_topics) else '',
                'hours': modules_hours[i-1] if i-1 < len(modules_hours) else ''
            })

        # prescribed books
        books_list = str(syllabus.books).split('\n') if syllabus.books else []
        books_details = json.loads(syllabus.books_details) if syllabus.books_details else []
        for i, title in enumerate(books_list, 1):
            detail = books_details[i-1] if i-1 < len(books_details) else {}
            prescribed_books.append({
                'index': i,
                'title': title,
                'authors': detail.get('authors', '') if isinstance(detail, dict) else '',
                'edition': detail.get('edition', '') if isinstance(detail, dict) else '',
                'publisher': detail.get('publisher', '') if isinstance(detail, dict) else '',
                'year': detail.get('year', '') if isinstance(detail, dict) else '',
            })

        # reference books
        ref_list = str(syllabus.reference_books).split('\n') if syllabus.reference_books else []
        ref_details = json.loads(syllabus.reference_books_details) if syllabus.reference_books_details else []
        for i, title in enumerate(ref_list, 1):
            detail = ref_details[i-1] if i-1 < len(ref_details) else {}
            reference_books.append({
                'index': i,
                'title': title,
                'authors': detail.get('authors', '') if isinstance(detail, dict) else '',
                'edition': detail.get('edition', '') if isinstance(detail, dict) else '',
                'publisher': detail.get('publisher', '') if isinstance(detail, dict) else '',
                'year': detail.get('year', '') if isinstance(detail, dict) else '',
            })

        # ebooks & moocs
        ebooks = [x for x in (str(syllabus.ebooks).split('\n') if syllabus.ebooks else []) if x]
        moocs = [x for x in (str(syllabus.moocs).split('\n') if syllabus.moocs else []) if x]
    except Exception:
        module_rows = []
        prescribed_books = []
        reference_books = []
        ebooks = []
        moocs = []

    context = {
        'course': course,
        'syllabus': syllabus,
        'initial_semester': getattr(course, 'semester', None),
        'semesters': range(1, 9),
        'module_rows': module_rows,
        'prescribed_books': prescribed_books,
        'reference_books': reference_books,
        'ebooks': ebooks,
        'moocs': moocs,
    }

    return render(request, 'facultymodule/edit_syllabus.html', context)


@login_required
def view_syllabus_pdf(request, course_allocation_id):
    """Return the latest saved FacultySyllabusPDF for a CourseAllocation (inline display)."""
    try:
        ca = get_object_or_404(CourseAllocation, pk=course_allocation_id)
        # try to find the linked CollegeLevelCourse
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
    except Exception:
        messages.error(request, "Required models not available.")
        return redirect('facultymodule:faculty_dashboard')

    course = CollegeLevelCourse.objects.filter(course_code=getattr(ca, 'course_code', None)).first()
    if not course:
        messages.error(request, "No course record found for this allocation.")
        return redirect('facultymodule:faculty_dashboard')

    pdf_row = FacultySyllabusPDF.objects.filter(course=course).order_by('-created_at').first()
    if not pdf_row or not getattr(pdf_row, 'pdf_file'):
        messages.error(request, "No generated PDF found for this course.")
        return redirect('facultymodule:faculty_dashboard')

    try:
        file_field = getattr(pdf_row, 'pdf_file')
        file_path = file_field.path
        return FileResponse(open(file_path, 'rb'), content_type='application/pdf')
    except Exception as e:
        logger.exception("Failed to serve saved PDF: %s", e)
        messages.error(request, "Failed to open the saved PDF.")
        return redirect('facultymodule:faculty_dashboard')


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

def generate_faculty_syllabus_pdf(request, course, syllabus, course_alloc=None):
    """
    Wrapper that generates the HOD-style syllabus PDF using
    generate_syllabus_pdf_buffer(...) and then attempts to save a copy
    into hod.FacultySyllabusPDF (defensive). Returns HttpResponse for download.
    """
    import logging
    import io
    from django.http import HttpResponse
    from django.core.files.base import ContentFile
    from django.apps import apps
    from django.utils import timezone
    from django.contrib import messages
    from django.shortcuts import redirect

    logger = logging.getLogger(__name__)

    # --- 1) build PDF buffer using the HOD-style generator if available ---
    try:
        # Prefer a direct import from the known module (hod.pdf_generator)
        pdf_buf = None
        try:
            # If this module defines it already, use that.
            if 'generate_syllabus_pdf_buffer' in globals() and callable(globals()['generate_syllabus_pdf_buffer']):
                try:
                    pdf_buf = globals()['generate_syllabus_pdf_buffer'](syllabus)
                except Exception:
                    logger.exception("Local generate_syllabus_pdf_buffer raised an exception")
                    pdf_buf = None

            # Try hod.pdf_generator if still missing
            if pdf_buf is None:
                try:
                    from hod.pdf_generator import generate_syllabus_pdf_buffer as _gen_buf
                    try:
                        pdf_buf = _gen_buf(syllabus)
                    except Exception:
                        logger.exception("hod.pdf_generator.generate_syllabus_pdf_buffer raised an exception")
                        pdf_buf = None
                except Exception:
                    logger.debug("Could not import generate_syllabus_pdf_buffer from hod.pdf_generator", exc_info=True)
                    pdf_buf = None

            # Try academics.views (current known location) as a fallback
            if pdf_buf is None:
                try:
                    from academics.views import generate_syllabus_pdf_buffer as _acad_gen
                    try:
                        pdf_buf = _acad_gen(syllabus)
                    except Exception:
                        logger.exception("academics.views.generate_syllabus_pdf_buffer raised an exception")
                        pdf_buf = None
                except Exception:
                    logger.debug("Could not import generate_syllabus_pdf_buffer from academics.views", exc_info=True)
                    pdf_buf = None
        except Exception as e:
            logger.exception("Failed to obtain PDF buffer from generator: %s", e)
            pdf_buf = None

        if pdf_buf is None:
            logger.error("HOD PDF generator not found; cannot create PDF.")
            messages.error(request, "Internal error: PDF generator missing. Please contact admin.")
            return redirect('facultymodule:faculty_dashboard')

        # ensure it's a BytesIO-like object
        if isinstance(pdf_buf, (bytes, bytearray)):
            pdf_bytes = bytes(pdf_buf)
        else:
            try:
                pdf_buf.seek(0)
            except Exception:
                pass
            pdf_bytes = pdf_buf.getvalue()
    except Exception as e:
        logger.exception("Error generating PDF buffer: %s", e)
        messages.error(request, "Failed to generate PDF.")
        return redirect('facultymodule:faculty_dashboard')

    # --- 2) Defensive save to hod.FacultySyllabusPDF (non-fatal) ---
    try:
        FacultySyllabusPDF = None
        try:
            FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
        except LookupError:
            FacultySyllabusPDF = None

        if FacultySyllabusPDF:
            # determine branch/year/sem heuristics (same logic as before)
            branch_obj = None
            year_val = None
            sem_val = None

            if course_alloc is not None:
                branch_obj = getattr(course_alloc, 'branch', None)
                year_val = getattr(course_alloc, 'admission_year', None) or getattr(course_alloc, 'year', None)
                sem_val = getattr(course_alloc, 'semester', None)

            try:
                # try to use any CourseAllocation model if present in project
                ca = None
                try:
                    # try common app names - adjust if you know the exact app
                    from academica.models import CourseAllocation as _CA
                except Exception:
                    _CA = None
                if _CA:
                    try:
                        ca = _CA.objects.filter(course_code=getattr(course, 'course_code', None)).first()
                    except Exception:
                        ca = None

                if ca:
                    branch_obj = branch_obj or getattr(ca, 'branch', None)
                    year_val = year_val or getattr(ca, 'admission_year', None) or getattr(ca, 'year', None)
                    sem_val = sem_val or getattr(ca, 'semester', None)
            except Exception:
                pass

            branch_obj = branch_obj or getattr(course, 'branch', None) or None

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

            desired_kwargs = {
                'branch': branch_obj,
                'year': str(year_val) if year_val is not None else '',
                'semester': str(sem_val) if sem_val is not None else (str(getattr(course, 'semester', '') or '')),
                'created_by': (request.user if hasattr(request, 'user') else None),
                'course': course,
                'title': getattr(course, 'course_title', '') or getattr(course, 'course_code', 'Syllabus'),
                'approved': False,
                'rejected': False,
            }

            model_field_names = {f.name for f in FacultySyllabusPDF._meta.get_fields() if getattr(f, 'concrete', False)}
            safe_kwargs = {k: v for k, v in desired_kwargs.items() if k in model_field_names}
            pdf_row = FacultySyllabusPDF.objects.create(**safe_kwargs)

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
        logger.exception("Failed to save faculty PDF (non-fatal): %s", e)

    # --- 3) Return PDF for download (final) ---
    try:
        # Prefer inline display so the browser can open the PDF. Also works as a download if user chooses.
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{getattr(course, "course_code", "syllabus")}_syllabus.pdf"'
        return response
    except Exception as e:
        logger.exception("Failed to build HTTP response for PDF: %s", e)
        messages.error(request, "Failed to return PDF.")
        return redirect('facultymodule:faculty_dashboard')


@login_required
def view_syllabus(request, course_allocation_id):
    """Render the saved syllabus in a read-only HTML page.

    This is intended for faculty to "view as is" without entering the edit form.
    """
    import json
    try:
        ca = get_object_or_404(CourseAllocation, pk=course_allocation_id)
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        Syllabus = apps.get_model('academics', 'Syllabus')
    except Exception:
        messages.error(request, "Required models not available.")
        return redirect('facultymodule:faculty_dashboard')

    course = CollegeLevelCourse.objects.filter(course_code=getattr(ca, 'course_code', None)).first()
    if not course:
        messages.error(request, "No course record found for this allocation.")
        return redirect('facultymodule:faculty_dashboard')

    syllabus = Syllabus.objects.filter(course=course).first()
    if not syllabus:
        messages.error(request, "No syllabus found for this course.")
        return redirect('facultymodule:faculty_dashboard')

    # Build display lists (same structure used by edit form)
    module_rows = []
    prescribed_books = []
    reference_books = []
    ebooks = []
    moocs = []
    try:
        modules_list = str(syllabus.modules).split('\n') if syllabus.modules else []
        modules_topics = json.loads(syllabus.modules_topics) if syllabus.modules_topics else []
        modules_hours = json.loads(syllabus.modules_hours) if syllabus.modules_hours else []
        for i, title in enumerate(modules_list, 1):
            module_rows.append({
                'index': i,
                'title': title,
                'topics': modules_topics[i-1] if i-1 < len(modules_topics) else '',
                'hours': modules_hours[i-1] if i-1 < len(modules_hours) else ''
            })

        books_list = str(syllabus.books).split('\n') if syllabus.books else []
        books_details = json.loads(syllabus.books_details) if syllabus.books_details else []
        for i, title in enumerate(books_list, 1):
            detail = books_details[i-1] if i-1 < len(books_details) else {}
            prescribed_books.append({
                'index': i,
                'title': title,
                'authors': detail.get('authors', '') if isinstance(detail, dict) else '',
                'edition': detail.get('edition', '') if isinstance(detail, dict) else '',
                'publisher': detail.get('publisher', '') if isinstance(detail, dict) else '',
                'year': detail.get('year', '') if isinstance(detail, dict) else '',
            })

        ref_list = str(syllabus.reference_books).split('\n') if syllabus.reference_books else []
        ref_details = json.loads(syllabus.reference_books_details) if syllabus.reference_books_details else []
        for i, title in enumerate(ref_list, 1):
            detail = ref_details[i-1] if i-1 < len(ref_details) else {}
            reference_books.append({
                'index': i,
                'title': title,
                'authors': detail.get('authors', '') if isinstance(detail, dict) else '',
                'edition': detail.get('edition', '') if isinstance(detail, dict) else '',
                'publisher': detail.get('publisher', '') if isinstance(detail, dict) else '',
                'year': detail.get('year', '') if isinstance(detail, dict) else '',
            })

        ebooks = [x for x in (str(syllabus.ebooks).split('\n') if syllabus.ebooks else []) if x]
        moocs = [x for x in (str(syllabus.moocs).split('\n') if syllabus.moocs else []) if x]
    except Exception:
        module_rows = []
        prescribed_books = []
        reference_books = []
        ebooks = []
        moocs = []

    context = {
        'course': course,
        'syllabus': syllabus,
        'module_rows': module_rows,
        'prescribed_books': prescribed_books,
        'reference_books': reference_books,
        'ebooks': ebooks,
        'moocs': moocs,
    }

    return render(request, 'facultymodule/view_syllabus.html', context)
