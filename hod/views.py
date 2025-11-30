import os
import logging
from io import BytesIO
from datetime import datetime
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import HttpResponse, FileResponse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods


# ReportLab imports
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# local user model
from users.models import CustomUser

logger = logging.getLogger(__name__)

# ---------- robust model imports ----------
# Try the most likely module paths for each model (Academics / Hod / Users).
# If a model truly isn't present, raise an explicit ImportError so you fix the app naming / INSTALLED_APPS.

def _import_model(path, model_name):
    """Try to import model by module path string; raise helpful error if missing."""
    try:
        module = __import__(path, fromlist=[model_name])
        return getattr(module, model_name)
    except Exception as e:
        raise ImportError(f"Cannot import {model_name} from {path}: {e}")

# academics models (primary)
Course = Branch = Syllabus = None
try:
    Course = _import_model('academics.models', 'CollegeLevelCourse')
    Branch = _import_model('academics.models', 'Branch')
    Syllabus = _import_model('academics.models', 'Syllabus')
except ImportError as e:
    # Fall back attempts (common alternate names/locations)
    logger.debug("Primary academics import failed: %s", e)
    try:
        Course = _import_model('academics.models', 'Course')
    except Exception:
        Course = None
    # Branch/Syllabus fallback not attempted further; we'll raise later if required.

# Hod / allocation & assignment models (where you keep CourseAllocation/FacultyAssignment)
CourseAllocation = FacultyAssignment = None
try:
    CourseAllocation = _import_model('hod.models', 'CourseAllocation')
    FacultyAssignment = _import_model('hod.models', 'FacultyAssignment')
except Exception:
    logger.debug("hod.models import failed for allocation/assignment, trying alternatives")
    # also try academia or local app
    try:
        CourseAllocation = _import_model('academics.models', 'CourseAllocation')
    except Exception:
        CourseAllocation = None
    try:
        FacultyAssignment = _import_model('academics.models', 'FacultyAssignment')
    except Exception:
        FacultyAssignment = None

# Faculty model — could live in users, faculty app or hod app. Try in order.
Faculty = None
for path, name in (('users.models', 'Faculty'), ('faculty.models', 'Faculty'), ('hod.models', 'Faculty')):
    try:
        Faculty = _import_model(path, name)
        break
    except Exception:
        logger.debug("Could not import Faculty from %s.%s", path, name)

# Optional: SyllabusSubmission (used somewhere else maybe)
SyllabusSubmission = None
try:
    SyllabusSubmission = _import_model('academics.models', 'SyllabusSubmission')
except Exception:
    logger.debug("SyllabusSubmission not found in academics.models; continuing.")

# Final sanity: if critical models are missing, raise an explanatory ImportError immediately.
_missing = []
if Course is None:
    _missing.append('CollegeLevelCourse (academics.models)')
if Branch is None:
    _missing.append('Branch (academics.models)')
if CourseAllocation is None:
    _missing.append('CourseAllocation (hod.models or academics.models)')
if FacultyAssignment is None:
    _missing.append('FacultyAssignment (hod.models or academics.models)')

if _missing:
    raise ImportError("Missing required models: " + ', '.join(_missing) +
                      ". Check app names, model names and INSTALLED_APPS.")



# ===== HELPER FUNCTION: BUILD SCHEME PDF BYTES =====
def _build_scheme_pdf_bytes(branch, year, semester, main_rows=None, elective_rows=None):
    """
    Build PDF bytes using ReportLab. If main_rows/elective_rows provided, use them;
    otherwise read from DB (CollegeLevelCourse + SchemeCourse).
    Returns bytes.
    """
    # if branch is an id -> load object
    if isinstance(branch, int):
        try:
            branch = apps.get_model('academics', 'Branch').objects.get(pk=branch)
        except Exception:
            branch = None

    # Fetch default rows if not provided
    if main_rows is None:
        main_rows = []
        try:
            CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
            dean_qs = CollegeLevelCourse.objects.filter(Q(branch__isnull=True) | Q(branch=branch))
            if hasattr(CollegeLevelCourse, 'semester'):
                try:
                    dean_qs = dean_qs.filter(semester=semester)
                except Exception:
                    pass
            for dc in dean_qs:
                main_rows.append({
                    'category': getattr(dc, 'course_category', '') or '',
                    'code': getattr(dc, 'course_code', '') or '',
                    'title': getattr(dc, 'course_title', '') or '',
                    'l': int(getattr(dc, 'teaching_hours_L', 0) or 0),
                    't': int(getattr(dc, 'teaching_hours_T', 0) or 0),
                    'p': int(getattr(dc, 'teaching_hours_P', 0) or 0),
                    'cie': int(getattr(dc, 'cie_marks', 0) or 0),
                    'see': int(getattr(dc, 'see_marks', 0) or 0),
                    'credits': str(getattr(dc, 'credits', 0) or 0),
                    'faculty_name': getattr(getattr(dc, 'faculty', None), 'get_full_name', lambda: getattr(getattr(dc, 'faculty', None), 'username', ''))()
                })
        except LookupError:
            logger.debug("CollegeLevelCourse model not found; skipping dean rows.")
        except Exception:
            logger.exception("Error while fetching dean rows")

        # Add SchemeCourse rows from hod app (if present)
        try:
            SchemeCourse = apps.get_model('hod', 'SchemeCourse')
            sc_qs = SchemeCourse.objects.filter(branch=branch.pk if branch else branch, year=year, semester=semester, is_elective=False)
            for sc in sc_qs:
                main_rows.append({
                    'category': getattr(sc, 'category', '') or '',
                    'code': sc.course_code,
                    'title': getattr(sc, 'course_title', '') or (getattr(sc, 'course', None) and getattr(sc.course, 'course_title', '') or ''),
                    'l': int(getattr(sc, 'l', 0) or 0),
                    't': int(getattr(sc, 't', 0) or 0),
                    'p': int(getattr(sc, 'p', 0) or 0),
                    'cie': int(getattr(sc, 'cie', 0) or 0),
                    'see': int(getattr(sc, 'see', 0) or 0),
                    'credits': getattr(sc, 'credits', 0) or 0,
                    'faculty_name': getattr(getattr(sc, 'faculty', None), 'get_full_name', lambda: getattr(getattr(sc, 'faculty', None), 'username', ''))()
                })
        except LookupError:
            logger.debug("SchemeCourse model not found; skipping HOD scheme rows.")
        except Exception:
            logger.exception("Error while fetching SchemeCourse rows")

    if elective_rows is None:
        elective_rows = []
        try:
            SchemeCourse = apps.get_model('hod', 'SchemeCourse')
            sc_qs = SchemeCourse.objects.filter(branch=branch.pk if branch else branch, year=year, semester=semester, is_elective=True)
            for sc in sc_qs:
                elective_rows.append({
                    'section': getattr(sc, 'category', 'ESC'),
                    'code': sc.course_code,
                    'title': getattr(sc, 'course_title', '') or '',
                    'faculty_name': getattr(getattr(sc, 'faculty', None), 'get_full_name', lambda: getattr(getattr(sc, 'faculty', None), 'username', ''))()
                })
        except LookupError:
            logger.debug("SchemeCourse model not found for electives.")
        except Exception:
            logger.exception("Error while fetching SchemeCourse electives")

    # Build PDF using ReportLab (same sizes & style as original)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.35*inch, bottomMargin=0.35*inch,
                            leftMargin=0.45*inch, rightMargin=0.45*inch)
    elements = []
    styles = getSampleStyleSheet()

    # Header area (logo + department)
    try:
        logo_path = os.path.join(settings.BASE_DIR, "users", "static", "images", "malnad_college_of_engineering_logo.jpeg")
        if branch and os.path.exists(logo_path):
            logo = RLImage(logo_path, width=0.6*inch, height=0.6*inch)
            header_content = Paragraph(
                "<b>MALNAD COLLEGE OF ENGINEERING, HASSAN</b><br/>(An Autonomous Institution Affiliated to VTU, Belagavi)<br/>"
                f"<b>DEPARTMENT OF {branch.name.upper()}</b>",
                ParagraphStyle('Header', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, fontName='Helvetica-Bold')
            )
            header_table = Table([[logo, header_content]], colWidths=[0.8*inch, 5.5*inch])
            header_table.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'), ('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
            elements.append(header_table)
        else:
            dept = branch.name.upper() if branch else "DEPARTMENT"
            elements.append(Paragraph(f"<b>MALNAD COLLEGE OF ENGINEERING, HASSAN</b><br/><b>DEPARTMENT OF {dept}</b>",
                                      ParagraphStyle('Header', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, fontName='Helvetica-Bold')))
    except Exception:
        logger.exception("Error while adding header to PDF")

    elements.append(Spacer(1, 0.05*inch))
    sem_name = ['','FIRST','SECOND','THIRD','FOURTH','FIFTH','SIXTH','SEVENTH','EIGHTH']
    sem_idx = int(semester) if isinstance(semester, (int, str)) else 0
    elements.append(Paragraph(f"<b>{sem_name[sem_idx] if sem_idx < len(sem_name) else 'SEM'} SEMESTER — {year}</b>",
                              ParagraphStyle('Semester', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, fontName='Helvetica-Bold', textColor=colors.HexColor('#008000'))))
    elements.append(Spacer(1, 0.08*inch))

    # Main table
    if main_rows:
        header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=6.5, alignment=TA_CENTER, fontName='Helvetica-Bold', leading=8)
        data_style = ParagraphStyle('Data', parent=styles['Normal'], fontSize=6.5, alignment=TA_CENTER, leading=8)
        title_style = ParagraphStyle('Title', parent=styles['Normal'], fontSize=6.5, alignment=TA_LEFT, leading=8)

        table_data = [[
            Paragraph('Sl.<br/>No', header_style),
            Paragraph('Course<br/>Category', header_style),
            Paragraph('Course<br/>Code', header_style),
            Paragraph('Course Title', header_style),
            Paragraph('Teaching<br/>Hours/Week', header_style),
            Paragraph('L', header_style),
            Paragraph('T', header_style),
            Paragraph('P', header_style),
            Paragraph('Total', header_style),
            Paragraph('Exam<br/>Marks', header_style),
            Paragraph('CIE', header_style),
            Paragraph('SEE', header_style),
            Paragraph('Total', header_style),
            Paragraph('Credits', header_style),
            Paragraph('Assign<br/>Faculty', header_style),
        ]]

        row_num = 1
        for row in main_rows:
            # ensure numeric conversion safety
            l = int(row.get('l') or 0)
            t = int(row.get('t') or 0)
            p = int(row.get('p') or 0)
            cie = int(row.get('cie') or 0)
            see = int(row.get('see') or 0)
            total_hours = l + t + p
            total_marks = cie + see
            credits = row.get('credits', '')
            table_data.append([
                Paragraph(str(row_num), data_style),
                Paragraph(row.get('category',''), data_style),
                Paragraph(row.get('code',''), data_style),
                Paragraph(row.get('title',''), title_style),
                Paragraph('', data_style),
                Paragraph(str(l), data_style),
                Paragraph(str(t), data_style),
                Paragraph(str(p), data_style),
                Paragraph(str(total_hours), data_style),
                Paragraph('', data_style),
                Paragraph(str(cie), data_style),
                Paragraph(str(see), data_style),
                Paragraph(str(total_marks), data_style),
                Paragraph(str(credits), data_style),
                Paragraph(row.get('faculty_name',''), data_style),
            ])
            row_num += 1

        col_widths = [0.35*inch, 0.75*inch, 0.75*inch, 2.1*inch, 0.45*inch, 0.45*inch, 0.45*inch, 0.45*inch, 0.45*inch, 0.35*inch, 0.35*inch, 0.4*inch, 0.4*inch, 0.7*inch]
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#8ADBE9")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 6.5),
            ('TOPPADDING', (0, 0), (-1, 0), 3),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
            ('FONTSIZE', (0, 1), (-1, -1), 6.5),
            ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (3, 1), (3, -1), 'LEFT'),
            ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 1), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 2),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F2F2')]),
            ('LEFTPADDING', (3, 0), (3, -1), 2),
            ('RIGHTPADDING', (3, 0), (3, -1), 2),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.15*inch))

    # Elective sections
    if elective_rows:
        elective_sections = {}
        for row in elective_rows:
            elective_sections.setdefault(row.get('section','ESC'), []).append(row)

        elements.append(Paragraph("<b>Elective/Enhancement Courses</b>", ParagraphStyle('ET', parent=styles['Normal'], fontSize=10, alignment=TA_LEFT, fontName='Helvetica-Bold')))
        elements.append(Spacer(1, 0.08*inch))

        for section in ['PEC','OEC','ESC','AEC']:
            if section in elective_sections:
                section_courses = elective_sections[section]
                section_name = {'PEC':'Professional Elective Course (PEC)',
                                'OEC':'Open Elective Course (OEC)',
                                'ESC':'Engineering Science Course (ESC)',
                                'AEC':'Ability Enhancement Course (AEC)'}[section]
                elements.append(Paragraph(f"<b>{section_name}</b>", ParagraphStyle('SH', parent=styles['Normal'], fontSize=9, alignment=TA_LEFT, fontName='Helvetica-Bold', textColor=colors.HexColor('#4472C4'))))
                elements.append(Spacer(1, 0.05*inch))
                elective_header_style = ParagraphStyle('EH', parent=styles['Normal'], fontSize=7, alignment=TA_CENTER, fontName='Helvetica-Bold')
                elective_data_style = ParagraphStyle('ED', parent=styles['Normal'], fontSize=6.5, alignment=TA_LEFT)
                elective_table_data = [[Paragraph('Course Code', elective_header_style), Paragraph('Course Title', elective_header_style), Paragraph('Assign Faculty', elective_header_style)]]
                for course in section_courses:
                    elective_table_data.append([Paragraph(course.get('code',''), elective_data_style), Paragraph(course.get('title',''), elective_data_style), Paragraph(course.get('faculty_name',''), elective_data_style)])
                elective_table = Table(elective_table_data, colWidths=[1.0*inch, 3.5*inch, 1.5*inch])
                elective_table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#D9E1F2')), ('GRID',(0,0),(-1,-1),0.5,colors.grey), ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F9F9F9')])]))
                elements.append(elective_table)
                elements.append(Spacer(1, 0.1*inch))

    elements.append(Spacer(1, 0.05*inch))
    elements.append(Paragraph(f"Generated on {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}", ParagraphStyle('Footer', parent=styles['Normal'], fontSize=7, alignment=TA_CENTER, fontName='Helvetica-Oblique')))
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()

def _fetch_db_rows_for_scheme(branch, year, semester):
    """
    Fetch main and elective rows from database for PDF generation.
    Returns (main_rows, elective_rows) tuples.
    """
    main_rows = []
    elective_rows = []
    
    # Dean courses (CollegeLevelCourse)
    try:
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        dean_qs = CollegeLevelCourse.objects.filter(Q(branch__isnull=True) | Q(branch=branch))
        if hasattr(CollegeLevelCourse, 'semester'):
            try:
                dean_qs = dean_qs.filter(semester=semester)
            except Exception:
                pass
        
        for c in dean_qs:
            faculty_name = ''
            if getattr(c, 'faculty', None):
                faculty_name = c.faculty.get_full_name() or c.faculty.username
            
            main_rows.append({
                'category': getattr(c, 'course_category', '') or '',
                'code': getattr(c, 'course_code', '') or '',
                'title': getattr(c, 'course_title', '') or '',
                'l': int(getattr(c, 'teaching_hours_L', 0) or 0),
                't': int(getattr(c, 'teaching_hours_T', 0) or 0),
                'p': int(getattr(c, 'teaching_hours_P', 0) or 0),
                'cie': int(getattr(c, 'cie_marks', 0) or 0),
                'see': int(getattr(c, 'see_marks', 0) or 0),
                'credits': str(getattr(c, 'credits', 0) or 0),
                'faculty_name': faculty_name,
            })
    except LookupError:
        logger.debug("CollegeLevelCourse model not found")
    except Exception as e:
        logger.exception("Error fetching dean courses: %s", e)

    # HOD-created SchemeCourse rows (non-elective)
    try:
        SchemeCourse = apps.get_model('hod', 'SchemeCourse')
        sc_qs = SchemeCourse.objects.filter(
            branch=branch, 
            year=year, 
            semester=semester,
            is_elective=False
        )
        for sc in sc_qs:
            faculty_name = ''
            if getattr(sc, 'faculty', None):
                faculty_name = sc.faculty.get_full_name() or sc.faculty.username
            
            main_rows.append({
                'category': getattr(sc, 'category', '') or '',
                'code': sc.course_code,
                'title': getattr(sc, 'course_title', '') or '',
                'l': int(getattr(sc, 'l', 0) or 0),
                't': int(getattr(sc, 't', 0) or 0),
                'p': int(getattr(sc, 'p', 0) or 0),
                'cie': int(getattr(sc, 'cie', 0) or 0),
                'see': int(getattr(sc, 'see', 0) or 0),
                'credits': str(getattr(sc, 'credits', 0) or 0),
                'faculty_name': faculty_name,
            })
    except LookupError:
        logger.debug("SchemeCourse model not found")
    except Exception as e:
        logger.exception("Error fetching SchemeCourse rows: %s", e)

    # HOD-created SchemeCourse rows (electives only)
    try:
        SchemeCourse = apps.get_model('hod', 'SchemeCourse')
        sc_qs = SchemeCourse.objects.filter(
            branch=branch,
            year=year,
            semester=semester,
            is_elective=True
        )
        for sc in sc_qs:
            faculty_name = ''
            if getattr(sc, 'faculty', None):
                faculty_name = sc.faculty.get_full_name() or sc.faculty.username
            
            elective_rows.append({
                'section': getattr(sc, 'category', 'ESC') or 'ESC',
                'code': sc.course_code,
                'title': getattr(sc, 'course_title', '') or '',
                'faculty_name': faculty_name,
            })
    except LookupError:
        logger.debug("SchemeCourse model not found for electives")
    except Exception as e:
        logger.exception("Error fetching SchemeCourse electives: %s", e)

    return main_rows, elective_rows


# ===== REST OF YOUR VIEWS CONTINUE BELOW =====
@login_required
def dashboard_redirect(request):
    """Redirect /hod/dashboard/ to the HOD's assigned branch dashboard."""
    hod_assignment = getattr(request.user, 'hod_assignment', None)
    branch = getattr(hod_assignment, 'branch', None) if hod_assignment else None
    if not branch:
        # no branch assigned -> send to project root
        return redirect('/')
    return redirect('hod:dashboard_self', branch_pk=branch.pk)

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.apps import apps
import logging

logger = logging.getLogger(__name__)

@login_required
def dashboard(request, branch_pk=None):
    """Main HOD dashboard for a branch."""
    Branch = apps.get_model('academics', 'Branch')
    Course = None
    try:
        Course = apps.get_model('academics', 'CollegeLevelCourse')
    except LookupError:
        Course = None

    if not Branch or not Course:
        # academics app models not available
        return render(request, 'hod/hod_dashboard.html', {
            'branch': None, 'courses_dean': [], 'total_credits': 0, 'pending_submissions': [], 'selected_year': '', 'selected_semester': ''
        })

    if branch_pk is None:
        # no branch supplied — redirect to the HOD's assigned branch if possible
        return redirect('hod:dashboard_self') if hasattr(request.user, 'hod_assignment') else redirect('home')
    else:
        branch = get_object_or_404(Branch, pk=branch_pk)

    # selected year and semester from querystring (dashboard shows semester credits/courses when both present)
    selected_year = request.GET.get('year', '').strip()
    selected_semester = request.GET.get('semester', '').strip()

    # ensure this variable always exists to avoid UnboundLocalError
    selected_sem_credit = None

    # get CollegeLevelCourse model (already attempted above, but re-fetch safely)
    try:
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
    except LookupError:
        CollegeLevelCourse = None

    courses_dean = []
    total_credits = 0

    # Only fetch semester credits and dean courses when admission year is provided.
    semester_rows = []
    semester_credit_obj = None
    if selected_year:
        try:
            SemesterCredit = apps.get_model('academics', 'SemesterCredit')
        except LookupError:
            semester_credit_obj = None
        else:
            # choose proper "not deleted" kwarg depending on model field name
            deleted_kw = {}
            field_names = [f.name for f in SemesterCredit._meta.get_fields()]
            if 'is_deleted' in field_names:
                deleted_kw['is_deleted'] = False
            elif 'deleted' in field_names:
                deleted_kw['deleted'] = False

            semester_credit_obj = SemesterCredit.objects.filter(branch=branch, admission_year=selected_year, **deleted_kw).first()
            if not semester_credit_obj:
                try:
                    semester_credit_obj = SemesterCredit.objects.filter(branch=branch, admission_year=int(selected_year), **deleted_kw).first()
                except Exception:
                    semester_credit_obj = None

            if semester_credit_obj:
                for i in range(1, 9):
                    val = None
                    for fname in (f"sem{i}", f"semester_{i}", f"sem_{i}", f"s{i}", f"credits_sem_{i}"):
                        if hasattr(semester_credit_obj, fname):
                            val = getattr(semester_credit_obj, fname)
                            break
                    if val is None and hasattr(semester_credit_obj, 'credits'):
                        credits_field = getattr(semester_credit_obj, 'credits')
                        try:
                            val = credits_field[i-1]
                        except Exception:
                            val = None
                    semester_rows.append((f"Semester {i}", val or 0))

                # if a semester was selected, pick its credit value
                if selected_semester:
                    try:
                        idx = int(selected_semester) - 1
                        selected_sem_credit = semester_rows[idx][1]
                    except Exception:
                        selected_sem_credit = None

    # Only display dean-provided courses after both year AND semester are selected
    if selected_year and selected_semester and CollegeLevelCourse:
        try:
            dean_qs = CollegeLevelCourse.objects.filter(Q(branch__isnull=True) | Q(branch=branch))
            # if model has semester field, filter by sem
            if hasattr(CollegeLevelCourse, 'semester'):
                try:
                    dean_qs = dean_qs.filter(semester=selected_semester)
                except Exception:
                    pass
        except Exception:
            dean_qs = CollegeLevelCourse.objects.none()

        # Convert to simple dicts (make faculty_id an int or None)
        courses_dean = []
        for c in dean_qs:
            f_id = None
            if hasattr(c, 'faculty_id') and getattr(c, 'faculty_id') not in (None, ''):
                try:
                    f_id = int(getattr(c, 'faculty_id'))
                except Exception:
                    try:
                        f_obj = getattr(c, 'faculty', None)
                        f_id = int(getattr(f_obj, 'id')) if f_obj else None
                    except Exception:
                        f_id = None

            courses_dean.append({
                'id': getattr(c, 'id', None),
                'category': getattr(c, 'course_category', '') or '',
                'course_code': getattr(c, 'course_code', '') or '',
                'course_title': getattr(c, 'course_title', '') or '',
                'l': int(getattr(c, 'teaching_hours_L', 0) or 0),
                't': int(getattr(c, 'teaching_hours_T', 0) or 0),
                'p': int(getattr(c, 'teaching_hours_P', 0) or 0),
                'total_hours': (int(getattr(c, 'teaching_hours_L', 0) or 0)
                                + int(getattr(c, 'teaching_hours_T', 0) or 0)
                                + int(getattr(c, 'teaching_hours_P', 0) or 0)),
                'cie': int(getattr(c, 'cie_marks', 0) or 0),
                'see': int(getattr(c, 'see_marks', 0) or 0),
                'total_marks': (int(getattr(c, 'cie_marks', 0) or 0)
                                + int(getattr(c, 'see_marks', 0) or 0)),
                'credits': getattr(c, 'credits', 0) or 0,
                'faculty_id': f_id,
                'faculty_username': getattr(getattr(c, 'faculty', None), 'username', '') if hasattr(c, 'faculty') else '',
            })

        # Attach latest syllabus pk per course (safe lookup)
        try:
            Syllabus = apps.get_model('academics', 'Syllabus')
            syllabus_map = {}
            created_field = 'created_on' if 'created_on' in [f.name for f in Syllabus._meta.get_fields()] else 'created_at'
            for s in Syllabus.objects.all().order_by(f'-{created_field}'):
                course_obj = getattr(s, 'course', None)
                if not course_obj:
                    continue
                course_pk = getattr(course_obj, 'pk', None)
                if course_pk and course_pk not in syllabus_map:
                    syllabus_map[course_pk] = s.pk
            for c in courses_dean:
                c['syllabus_pk'] = syllabus_map.get(c.get('id'))
        except LookupError:
            for c in courses_dean:
                c['syllabus_pk'] = None
    else:
        courses_dean = []

    # pending submissions (existing code)
    pending_submissions = []
    try:
        SyllabusSubmission = apps.get_model('academics', 'SyllabusSubmission')
    except LookupError:
        SyllabusSubmission = None

    if SyllabusSubmission:
        try:
            # Use case-insensitive match for 'pending' to be robust against inconsistent casing
            pending_submissions = SyllabusSubmission.objects.filter(course__branch=branch, status__iexact='pending')
        except Exception:
            pending_submissions = []

    # ---------- NEW: fetch faculty-generated PDFs that match branch/year/semester ----------
    faculty_pdfs = []
    try:
        PDFModel = apps.get_model('academics', 'FacultySyllabusPDF')  # change name here if your model differs
    except LookupError:
        PDFModel = None

    if PDFModel and selected_year and selected_semester:
        pdf_fields = [f.name for f in PDFModel._meta.get_fields()]
        created_field = 'created_at' if 'created_at' in pdf_fields else ('created_on' if 'created_on' in pdf_fields else None)

        # build filter kwargs using common field names
        pdf_filter = {}
        # branch
        if 'branch' in pdf_fields:
            pdf_filter['branch'] = branch
        # year: try a few names
        for year_field in ('year', 'academic_year', 'admission_year'):
            if year_field in pdf_fields:
                pdf_filter[year_field] = selected_year
                break
        # semester
        for sem_field in ('semester', 'sem'):
            if sem_field in pdf_fields:
                pdf_filter[sem_field] = selected_semester
                break

        try:
            qs = PDFModel.objects.filter(**pdf_filter)
            if created_field:
                qs = qs.order_by(f'-{created_field}')
            faculty_pdfs = qs
        except Exception:
            faculty_pdfs = PDFModel.objects.none()
    else:
        # empty queryset-like for template safety
        faculty_pdfs = PDFModel.objects.none() if PDFModel else []

    # robustly compute total credits (works for model instances *or* dicts)
    total_credits_dean = 0
    if courses_dean:
        for c in courses_dean:
            try:
                val = getattr(c, 'credits', None)
                if val is None and isinstance(c, dict):
                    val = c.get('credits', 0)
                total_credits_dean += int(val or 0)
            except Exception:
                try:
                    total_credits_dean += int(c.get('credits', 0))
                except Exception:
                    pass

    # total credits from scheme
    total_credits_schema = 0
    if selected_year and selected_semester:
        try:
            SemesterCredit = apps.get_model('academics', 'SemesterCredit')
            obj = SemesterCredit.objects.filter(branch=branch, admission_year=selected_year).first()
            if obj:
                sem_field = f"sem{selected_semester}"
                total_credits_schema = getattr(obj, sem_field, 0) or 0
        except Exception:
            total_credits_schema = 0

    context = {
        'branch': branch,
        'hod_assignment': getattr(request.user, 'hod_assignment', None),
        'courses_dean': courses_dean,
        'total_credits': total_credits,
        'pending_submissions': pending_submissions,
        'selected_year': selected_year,
        'selected_semester': selected_semester,
        'semester_rows': semester_rows,
        'selected_sem_credit': selected_sem_credit,
        'total_credits_dean': total_credits_dean,
        'total_credits_schema': total_credits_schema,
        # new: faculty-generated PDFs for this branch/year/sem
        'faculty_pdfs': faculty_pdfs,
    }
    return render(request, 'hod/hod_dashboard.html', context)

@require_POST
@login_required
def generate_start_pages(request, branch_pk):
    """
    Handle the form POST from hod_dashboard that starts/generates pages.
    Redirect back to the HOD dashboard for the branch and include the year in the querystring
    so semester credits are shown.
    """
    year = request.POST.get('academic_year', '').strip()
    base = reverse('hod:dashboard_self', args=[branch_pk])
    if year:
        url = f"{base}?{urlencode({'year': year})}"
    else:
        url = base
    # TODO: actual generation logic here
    return redirect(url)

@require_http_methods(["POST"])
@login_required
def generate_full_pdf(request, branch_pk):
    """Generate full syllabus PDF (pages 1-14 + schemas + syllabi)."""
    branch = get_object_or_404(Branch, pk=branch_pk)
    year = request.POST.get('academic_year', '')
    messages.success(request, f'Full syllabus PDF for {year} generated successfully.')
    # redirect back to dashboard and preserve the year in querystring (so view shows credits)
    base = reverse('hod:dashboard_self', args=[branch_pk])
    if year:
        return redirect(f"{base}?{urlencode({'year': year})}")
    return redirect(base)

# lightweight placeholders so URL reversing / linking never raises template errors
@login_required
def view_schema(request, course_pk):
    return redirect('hod:hod_dashboard')

@login_required
def edit_schema(request, course_pk):
    return redirect('hod:hod_dashboard')

@login_required
def assign_faculty(request, course_pk):
    return redirect('hod:hod_dashboard')

@login_required
def view_submission(request, submission_pk):
    return redirect('hod:hod_dashboard')

@require_http_methods(["POST"])
@login_required
def approve_syllabus(request, submission_pk):
    # Approve a syllabus submission (academics.SyllabusSubmission)
    from django.apps import apps
    try:
        SyllabusSubmission = apps.get_model('academics', 'SyllabusSubmission')
    except LookupError:
        messages.error(request, 'Syllabus submission model not available.')
        return redirect(request.META.get('HTTP_REFERER') or reverse('hod:dashboard_self', args=[getattr(request.user, 'hod_assignment').branch.pk if hasattr(request.user, 'hod_assignment') else 0]))

    sub = get_object_or_404(SyllabusSubmission, pk=submission_pk)
    # mark approved
    try:
        sub.status = 'approved'
        sub.approved_by = request.user
        sub.approved_at = timezone.now()
        sub.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        messages.success(request, f'Syllabus for {sub.course.course_code} approved.')
    except Exception as e:
        logger.exception('Failed to approve syllabus submission %s: %s', submission_pk, e)
        messages.error(request, 'Failed to approve submission.')

    # Redirect back
    return redirect(request.META.get('HTTP_REFERER') or reverse('hod:dashboard_self', args=[getattr(request.user, 'hod_assignment').branch.pk if hasattr(request.user, 'hod_assignment') else 0]))

@require_POST
@login_required
def select_semester(request, branch_pk):
    """Receive year+semester from dashboard and redirect to edit_semester_schema.
    Additionally generate starting pages PDF (1..7) for the branch+year.
    """
    year = request.POST.get('academic_year') or request.POST.get('year') or request.GET.get('year','').strip()
    sem = request.POST.get('semester')
    if not year or not sem:
        messages.error(request, 'Please provide an admission year and select a semester.')
        return redirect(reverse('hod:dashboard_self', args=[branch_pk]))
    try:
        y = int(year)
        s = int(sem)
    except Exception:
        messages.error(request, 'Invalid year or semester.')
        return redirect(reverse('hod:dashboard_self', args=[branch_pk]))

    # Try to generate starting pages PDF for this branch+admission year.
    try:
        Branch = apps.get_model('academics', 'Branch')
        branch = get_object_or_404(Branch, pk=branch_pk)
        try:
            pdf_path = pdf_generator.generate_start_pages_pdf(branch, y)
            messages.success(request, f'Starting pages generated: {pdf_path}')
        except ImportError as ie:
            messages.error(request, f"PDF generation dependency missing: {ie}. Install with: pip install reportlab")
        except Exception as e:
            logging.exception("Failed to generate starting pages PDF")
            messages.error(request, f"Failed to generate starting pages: {e}")
    except Exception:
        # if academics.Branch does not exist or any other reason, silently proceed to edit page
        branch = None

    return redirect(reverse('hod:edit_semester_schema', args=[branch_pk, y, s]))


@login_required
def edit_semester_schema(request, branch_pk, year, sem):
    """
    Page where HOD can manage schemas for a particular branch+admission year+semester.
    Populate with subjects for that branch/sem if Subject model exists.
    """
    branch = get_object_or_404(Branch, pk=branch_pk)

    # try to load Subject model and fetch semester subjects
    subjects = []
    try:
        Subject = apps.get_model('academics', 'Subject')

        # detect available field names on Subject to avoid FieldError
        field_names = {f.name for f in Subject._meta.get_fields()}

        # pick a semester-like field if present
        sem_field = None
        for cand in ('semester', 'sem', 'semester_no', 'semester_number', 'term'):
            if cand in field_names:
                sem_field = cand
                break

        # build filter kwargs: always filter by branch if available on model
        filter_kwargs = {}
        if 'branch' in field_names:
            filter_kwargs['branch'] = branch

        # add semester filter only if model supports it
        if sem_field:
            # keep sem as int when appropriate
            try:
                filter_kwargs[sem_field] = int(sem)
            except Exception:
                filter_kwargs[sem_field] = sem

        # choose a safe ordering field
        order_field = None
        for cand in ('subject_code', 'code', 'course_code', 'title', 'id'):
            if cand in field_names:
                order_field = cand
                break

        qs = Subject.objects.filter(**filter_kwargs)
        subjects = list(qs.order_by(order_field) if order_field else qs)
    except LookupError:
        subjects = []

    context = {
        'branch': branch,
        'year': year,
        'semester': sem,
        'subjects': subjects,
    }
    return render(request, 'hod/edit_semester_schema.html', context)

@login_required
def create_scheme_form(request, branch_pk, year, semester):
    """GET-only form for creating a scheme (no POST handling here)."""
    branch = get_object_or_404(Branch, pk=branch_pk)
    
    # safe dean course queryset for branch or college-wide
    try:
        dean_qs = Course.objects.filter(Q(branch__isnull=True) | Q(branch=branch))
        # if model has semester field, filter by sem
        if hasattr(Course, 'semester'):
            try:
                dean_qs = dean_qs.filter(semester=semester)
            except Exception:
                # if semester field uses string/other format, try cast
                pass
    except Exception:
        dean_qs = Course.objects.none()

    # Convert to simple dicts (make faculty_id an int or None)
    dean_courses = []
    for c in dean_qs:
        # safely get faculty id as int if present
        f_id = None
        if hasattr(c, 'faculty_id') and getattr(c, 'faculty_id') not in (None, ''):
            try:
                f_id = int(getattr(c, 'faculty_id'))
            except Exception:
                try:
                    # if c.faculty is a relation
                    f_obj = getattr(c, 'faculty', None)
                    f_id = int(getattr(f_obj, 'id')) if f_obj else None
                except Exception:
                    f_id = None

        dean_courses.append({
            'id': getattr(c, 'id', None),
            'category': getattr(c, 'course_category', '') or '',
            'course_code': getattr(c, 'course_code', '') or '',
            'course_title': getattr(c, 'course_title', '') or '',
            'l': int(getattr(c, 'teaching_hours_L', 0) or 0),
            't': int(getattr(c, 'teaching_hours_T', 0) or 0),
            'p': int(getattr(c, 'teaching_hours_P', 0) or 0),
            'total_hours': (int(getattr(c, 'teaching_hours_L', 0) or 0)
                            + int(getattr(c, 'teaching_hours_T', 0) or 0)
                            + int(getattr(c, 'teaching_hours_P', 0) or 0)),
            'cie': int(getattr(c, 'cie_marks', 0) or 0),
            'see': int(getattr(c, 'see_marks', 0) or 0),
            'total_marks': (int(getattr(c, 'cie_marks', 0) or 0)
                            + int(getattr(c, 'see_marks', 0) or 0)),
            'credits': getattr(c, 'credits', 0) or 0,
            'faculty_id': f_id,
            'faculty_username': getattr(getattr(c, 'faculty', None), 'username', '') if hasattr(c, 'faculty') else '',
        })
    
    faculty_list = CustomUser.objects.filter(role='faculty', is_active=True)
    
    context = {
        'branch': branch,
        'year': year,
        'semester': semester,
        'dean_courses': dean_courses,
        'faculty_list': faculty_list,
    }
    return render(request, 'hod/create_scheme.html', context)


@login_required
def generate_pdf_view(request, branch_pk, year, semester):
    """
    Generate complete scheme PDF with cover + scheme table + support pages.
    - Always fetches dean courses from DB as base
    - If POST has form rows: merges them with dean rows
    - Otherwise: merges dean rows with any saved HOD scheme courses
    - Saves to SchemeDocument
    """
    try:
        branch = get_object_or_404(apps.get_model('academics', 'Branch'), pk=branch_pk)
    except Exception:
        messages.error(request, "Branch not found.")
        return redirect('hod:hod_dashboard')

    # --- FETCH DEAN COURSES FIRST (ALWAYS) ---
    dean_rows = []
    try:
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        dean_qs = CollegeLevelCourse.objects.filter(Q(branch__isnull=True) | Q(branch=branch))
        # filter by semester only if model has that field
        if hasattr(CollegeLevelCourse, 'semester'):
            try:
                dean_qs = dean_qs.filter(semester=int(semester))
            except Exception:
                dean_qs = dean_qs.filter(semester=semester)

        for dc in dean_qs:
            # safe numeric field extraction
            l = int(getattr(dc, 'teaching_hours_L', 0) or 0)
            t = int(getattr(dc, 'teaching_hours_T', 0) or 0)
            p = int(getattr(dc, 'teaching_hours_P', 0) or 0)
            cie = int(getattr(dc, 'cie_marks', 0) or 0)
            see = int(getattr(dc, 'see_marks', 0) or 0)
            credits = getattr(dc, 'credits', 0) or 0

            # Faculty detection: prefer relation, fallback to faculty_id
            faculty_name = ''
            if hasattr(dc, 'faculty') and getattr(dc, 'faculty'):
                f = getattr(dc, 'faculty')
                if callable(getattr(f, 'get_full_name', None)):
                    faculty_name = f.get_full_name() or getattr(f, 'username', str(f))
                else:
                    faculty_name = getattr(f, 'username', str(f))
            else:
                fid = getattr(dc, 'faculty_id', None)
                if fid:
                    try:
                        fu = CustomUser.objects.get(pk=fid)
                        faculty_name = fu.get_full_name() or fu.username
                    except Exception:
                        faculty_name = ''

            dean_rows.append({
                'category': getattr(dc, 'course_category', '') or '',
                'code': getattr(dc, 'course_code', '') or '',
                'title': getattr(dc, 'course_title', '') or '',
                'l': l,
                't': t,
                'p': p,
                'cie': cie,
                'see': see,
                'credits': str(credits),
                'faculty_name': faculty_name,
            })
    except LookupError:
        logger.debug("CollegeLevelCourse model not found")
        dean_rows = []
    except Exception as e:
        logger.exception("Error fetching dean courses: %s", e)
        dean_rows = []

    # Collect posted main_rows with faculty names
    posted_main_rows = []
    posted_elective_rows = []
    found_post = False
    
    i = 1
    while True:
        code = request.POST.get(f'code_new_{i}', '').strip()
        title = request.POST.get(f'title_new_{i}', '').strip()
        if not code and not title:
            break
        found_post = True
        
        faculty_name = ''
        faculty_id = request.POST.get(f'faculty_new_{i}')
        if faculty_id:
            try:
                u = CustomUser.objects.get(pk=int(faculty_id))
                faculty_name = u.get_full_name() or u.username
            except Exception:
                faculty_name = ''
        
        posted_main_rows.append({
            'category': request.POST.get(f'category_new_{i}', '') or '',
            'code': code,
            'title': title,
            'l': int(request.POST.get(f'l_new_{i}', 0) or 0),
            't': int(request.POST.get(f't_new_{i}', 0) or 0),
            'p': int(request.POST.get(f'p_new_{i}', 0) or 0),
            'cie': int(request.POST.get(f'cie_new_{i}', 0) or 0),
            'see': int(request.POST.get(f'see_new_{i}', 0) or 0),
            'credits': request.POST.get(f'credits_new_{i}', '0') or '0',
            'faculty_name': faculty_name,
        })
        i += 1

    # Collect posted elective rows with faculty names
    for section in ['pec', 'oec', 'esc', 'aec']:
        j = 1
        while True:
            code = request.POST.get(f'{section}_code_{j}', '').strip()
            title = request.POST.get(f'{section}_title_{j}', '').strip()
            if not code and not title:
                break
            found_post = True
            
            faculty_name = ''
            faculty_id = request.POST.get(f'{section}_faculty_{j}')
            if faculty_id:
                try:
                    u = CustomUser.objects.get(pk=int(faculty_id))
                    faculty_name = u.get_full_name() or u.username
                except Exception:
                    faculty_name = ''
            
            posted_elective_rows.append({
                'section': section.upper(),
                'code': code,
                'title': title,
                'faculty_name': faculty_name,
            })
            j += 1

    # Build final main_rows: dean rows + posted/DB rows
    main_rows = dean_rows[:]  # Start with dean rows
    elective_rows = posted_elective_rows[:]
    
    if found_post:
        # Merge posted rows with dean rows
        main_rows.extend(posted_main_rows)
    else:
        # If no POST, fetch any saved HOD scheme courses from DB
        hod_scheme_rows = _fetch_db_rows_for_scheme(branch, int(year), int(semester))
        if isinstance(hod_scheme_rows, tuple):
            hod_main, hod_elec = hod_scheme_rows
            main_rows.extend(hod_main)
            elective_rows.extend(hod_elec)
        else:
            # Fallback if function returns different format
            main_rows.extend(hod_scheme_rows)

    # Build PDF bytes
    pdf_bytes = _build_complete_scheme_pdf(branch, int(year), int(semester),
                                           main_rows=main_rows,
                                           elective_rows=elective_rows)

    if not pdf_bytes:
        messages.error(request, "Failed to generate PDF. No courses found.")
        return redirect('hod:dashboard_self', branch_pk=branch_pk)

    # Save to SchemeDocument
    filename = f"Scheme_{branch.name.replace(' ','_')}_{year}_Sem{semester}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        sd = SchemeDocument.objects.create(
            branch=branch,  # ← Make sure this is the branch OBJECT, not pk
            branch_name=branch.name, 
            year=int(year), 
            semester=int(semester), 
            title=f"{branch.name} Scheme Sem{semester} {year}", 
            created_by=request.user,
            is_deleted=False  # ← Ensure this is set to False
        )
        sd.pdf_file.save(filename, ContentFile(pdf_bytes))
        sd.save()
        messages.success(request, "Scheme PDF generated and saved successfully.")
        logger.info("SchemeDocument created: %s (branch=%s, year=%s, sem=%s, user=%s)", 
                    sd.pk, branch.name, year, semester, request.user.username)
    except Exception as e:
        logger.exception("Failed to save SchemeDocument: %s", e)
        messages.warning(request, f"PDF generated but failed to store in history: {e}")

    # Return download response
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

# Add this complete helper function to build the full scheme PDF

def _build_complete_scheme_pdf(branch, year, semester, main_rows=None, elective_rows=None):
    """
    Build a complete scheme PDF with:
    1. Cover page with border
    2. Vision & Mission page with border
    3. PEOs & POs page with border
    4. POs & PSOs page with border
    5. Scheme of Evaluation page with border
    6. Course Types page with border
    7. Scheme table page with border
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    
    # ===== CUSTOM CANVAS CLASS FOR BORDERS ON EVERY PAGE =====
    class BorderedPageCanvas(canvas.Canvas):
        """Canvas that draws green borders on every page"""
        def __init__(self, *args, **kwargs):
            canvas.Canvas.__init__(self, *args, **kwargs)
            self._pagesize = A4

        def showPage(self):
            """Draw border before showing page"""
            border_margin = 0.2 * inch
            page_width, page_height = self._pagesize
            
            self.setLineWidth(2)
            self.setStrokeColor(colors.HexColor("#008000"))  # Green border
            self.rect(
                border_margin,
                border_margin,
                page_width - (2 * border_margin),
                page_height - (2 * border_margin),
                stroke=1,
                fill=0
            )
            canvas.Canvas.showPage(self)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch,
        leftMargin=0.6*inch,
        rightMargin=0.6*inch
    )
    elements = []
    styles = getSampleStyleSheet()

    # ===== PAGE 1: COVER PAGE =====
    try:
        from reportlab.platypus import Image as RLImage
        logo_path = os.path.join(settings.BASE_DIR, "users", "static", "images", "malnad_college_of_engineering_logo.jpeg")
        if os.path.exists(logo_path):
            logo = RLImage(logo_path, width=1.2*inch, height=1.2*inch)
            elements.append(Spacer(1, 0.3*inch))
            logo_table = Table([[logo]], colWidths=[1.2*inch])
            logo_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
            elements.append(logo_table)
            elements.append(Spacer(1, 0.2*inch))
    except Exception as e:
        logger.warning("Could not add logo: %s", e)

    elements.append(Paragraph(
        "<b>MALNAD COLLEGE OF ENGINEERING, HASSAN</b><br/>"
        "(An Autonomous Institution Affiliated to VTU, Belagavi)",
        ParagraphStyle('CoverTitle', parent=styles['Normal'], fontSize=12, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.3*inch))

    elements.append(Paragraph(
        "<b>Autonomous Programme</b><br/><b>Bachelor of Engineering</b>",
        ParagraphStyle('Program', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.4*inch))

    if branch:
        elements.append(Paragraph(
            f"<b>Department Of<br/>{branch.name.upper()}</b>",
            ParagraphStyle('Dept', parent=styles['Normal'], fontSize=12, alignment=TA_CENTER, fontName='Times-Bold', textColor=colors.HexColor('#008000'))
        ))
    elements.append(Spacer(1, 0.5*inch))

    elements.append(Paragraph(
        f"<b>SCHEME AND SYLLABUS</b><br/><b>(2023 Admitted Batch)</b><br/><br/><b>Academic Year {year}-{year+1}</b>",
        ParagraphStyle('SchemeInfo', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, fontName='Times-Bold')
    ))

    elements.append(PageBreak())

    # ===== PAGE 2: VISION & MISSION =====
    elements.append(Paragraph(
        "<b>VISION OF THE INSTITUTE</b>",
        ParagraphStyle('SectionTitle', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.08*inch))
    elements.append(Paragraph(
        "To be an institute of excellence in engineering education and research, producing socially responsible professionals.",
        ParagraphStyle('Vision', parent=styles['Normal'], fontSize=9, alignment=TA_JUSTIFY, leading=11, fontName='Times-Roman')
    ))
    elements.append(Spacer(1, 0.15*inch))

    elements.append(Paragraph(
        "<b>MISSION OF THE INSTITUTE</b>",
        ParagraphStyle('SectionTitle', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.08*inch))
    mission_points = [
        "Create conducive environment for learning and research",
        "Establish industry and academia collaborations",
        "Ensure professional and ethical values in all institutional endeavors"
    ]
    for point in mission_points:
        elements.append(Paragraph(f"• {point}", ParagraphStyle('MissionPoint', parent=styles['Normal'], fontSize=9, alignment=TA_JUSTIFY, leading=10, fontName='Times-Roman')))
    
    elements.append(Spacer(1, 0.15*inch))

    if branch:
        elements.append(Paragraph(
            f"<b>VISION OF THE {branch.name.upper()} DEPARTMENT</b>",
            ParagraphStyle('DeptTitle', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, fontName='Times-Bold')
        ))
        elements.append(Spacer(1, 0.08*inch))
        elements.append(Paragraph(
            "The department will be a premier centre focusing on knowledge dissemination and generation to address the emerging needs of information technology in diverse fields.",
            ParagraphStyle('DeptVision', parent=styles['Normal'], fontSize=8, alignment=TA_JUSTIFY, leading=10, fontName='Times-Roman')
        ))
        elements.append(Spacer(1, 0.12*inch))

        elements.append(Paragraph(
            f"<b>MISSION OF THE {branch.name.upper()} DEPARTMENT</b>",
            ParagraphStyle('DeptMission', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, fontName='Times-Bold')
        ))
        elements.append(Spacer(1, 0.08*inch))
        dept_mission = [
            "1. To make students competent to contribute towards the development of IT field.",
            "2. Promote learning and practice of latest tools and technologies among students and prepare them for diverse career options.",
            "3. Collaborate with industry and institutes of higher learning for Research and Development, innovations and continuing education.",
            "4. Developing capacity of teachers in terms of their teaching and research abilities.",
            "5. Develop software applications to solve engineering and societal problems."
        ]
        for point in dept_mission:
            elements.append(Paragraph(f"{point}", ParagraphStyle('DeptPoint', parent=styles['Normal'], fontSize=8, alignment=TA_JUSTIFY, leading=10, fontName='Times-Roman')))

    elements.append(PageBreak())

    # ===== PAGE 3: PEOs & POs =====
    elements.append(Paragraph(
        "<b>PROGRAM EDUCATIONAL OBJECTIVES (PEOs)</b>",
        ParagraphStyle('PEOTitle', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.08*inch))
    
    elements.append(Paragraph(
        "<b>Graduates will:</b>",
        ParagraphStyle('GraduatesWill', parent=styles['Normal'], fontSize=9, alignment=TA_LEFT, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.05*inch))
    
    peo_points = [
        "<b>PEO1:</b> Be successful professionals in IT industry with good design, coding and testing skills, capable of assimilating new information and solve new problems.",
        "<b>PEO2:</b> Communicate proficiently and collaborate successfully with peers, colleagues and organizations.",
        "<b>PEO3:</b> Be ethical and responsible members of the computing profession and society.",
        "<b>PEO4:</b> Acquire necessary skills for research, higher studies, entrepreneurship and continued learning to adopt and create new applications."
    ]
    
    for point in peo_points:
        elements.append(Paragraph(point, ParagraphStyle('PEOPoint', parent=styles['Normal'], fontSize=8, alignment=TA_JUSTIFY, leading=10, fontName='Times-Roman')))
        elements.append(Spacer(1, 0.05*inch))

    elements.append(Spacer(1, 0.1*inch))
    
    elements.append(Paragraph(
        "<b>PROGRAM OUTCOMES (POs)</b>",
        ParagraphStyle('POTitle', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.08*inch))
    
    po_points_page3 = [
        "<b>1. Engineering knowledge:</b> Apply knowledge of mathematics, natural science, computing, engineering fundamentals and an engineering specialization as specified in WK1 to WK4 respectively to develop to the solution of complex engineering problems.",
        "<b>2. Problem analysis:</b> Identify, formulate, review research literature, and analyze complex engineering problems reaching substantiated conclusions with consideration for sustainable development. (WK1 to WK4)",
        "<b>3. Design/Development of solutions:</b> Design creative solutions for complex engineering problems and design/develop systems/components/processes to meet identified needs with consideration for the public health and safety, whole-life cost, net zero carbon, culture, society and environment as required. (WK5)",
        "<b>4. Conduct investigations of complex problems:</b> Conduct investigations of complex engineering problems using research-based knowledge including design of experiments, modelling, analysis & interpretation of data to provide valid conclusions. (WK8).",
        "<b>5. Modern tool usage:</b> Create, select and apply appropriate techniques, resources and modern engineering & IT tools, including prediction and modelling recognizing their limitations to solve complex engineering problems. (WK2 and WK6)",
        "<b>6. The engineer and the world:</b> Analyze and evaluate societal and environmental aspects while solving complex engineering problems for its impact on sustainability with reference to economy, health, safety, legal framework, culture and environment. (WK1, WK5, and WK7)."
    ]
    
    for point in po_points_page3:
        elements.append(Paragraph(point, ParagraphStyle('POPoint', parent=styles['Normal'], fontSize=7.5, alignment=TA_JUSTIFY, leading=9, fontName='Times-Roman')))
        elements.append(Spacer(1, 0.04*inch))

    elements.append(PageBreak())

    # ===== PAGE 4: POs continued & PSOs =====
    elements.append(Paragraph(
        "<b>PROGRAM OUTCOMES (POs) - Continued</b>",
        ParagraphStyle('POTitle2', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.08*inch))
    
    po_points_page4 = [
        "<b>7. Environment and sustainability:</b> Understand the impact of the professional engineering solutions in societal and environmental contexts, and demonstrate the knowledge of, and need for sustainable development.",
        "<b>8. Ethics:</b> Apply ethical principles and commit to professional ethics, human values, diversity and inclusion; adhere to national & international laws. (WK9)",
        "<b>9. Individual and collaborative team work:</b> Function effectively as an individual, and as a member or leader in diverse/multi-disciplinary settings.",
        "<b>10. Communication:</b> Communicate effectively and inclusively within the community and society at large, such as being able to comprehend and write effective reports and design documentation, make effective presentations considering cultural, language, and learning differences.",
        "<b>11. Project management and finance:</b> Apply knowledge and understanding of engineering management principles and economic decision-making and apply these to one's own work, as a member and leader in a team, and to manage projects and in multidisciplinary environments.",
        "<b>12. Life-long learning:</b> Recognize the need for, and have the preparation and ability for i) independent and life-long learning ii) adaptability to new and emerging technologies and iii) critical thinking in the broadest context of technological change. (WK8)"
    ]
    
    for point in po_points_page4:
        elements.append(Paragraph(point, ParagraphStyle('POPoint', parent=styles['Normal'], fontSize=7.5, alignment=TA_JUSTIFY, leading=9, fontName='Times-Roman')))
        elements.append(Spacer(1, 0.04*inch))

    elements.append(Spacer(1, 0.1*inch))
    
    elements.append(Paragraph(
        "<b>PROGRAM SPECIFIC OUTCOMES (PSOs)</b>",
        ParagraphStyle('PSOTitle', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.08*inch))
    
    pso_intro = "Upon graduation, students with a degree B.E. in Information Science & Engineering will be able to:"
    elements.append(Paragraph(pso_intro, ParagraphStyle('PSOIntro', parent=styles['Normal'], fontSize=9, alignment=TA_JUSTIFY, leading=10, fontName='Times-Roman')))
    elements.append(Spacer(1, 0.08*inch))
    
    pso_points = [
        "Design and Develop efficient information systems for organizational needs.",
        "Ability to adopt software engineering principles and work with various standards of Computing Systems."
    ]
    
    for point in pso_points:
        elements.append(Paragraph(f"• {point}", ParagraphStyle('PSOPoint', parent=styles['Normal'], fontSize=8, alignment=TA_JUSTIFY, leading=10, fontName='Times-Roman')))
        elements.append(Spacer(1, 0.06*inch))

    elements.append(PageBreak())

    # ===== PAGE 5: SCHEME OF EVALUATION =====
    elements.append(Paragraph(
        "<b>SCHEME OF EVALUATION (THEORY COURSES)</b>",
        ParagraphStyle('EvalTitle', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.12*inch))

    theory_eval_data = [
        ['Assessment', 'Marks'],
        ['CIE 1', '10'],
        ['CIE 2', '10'],
        ['CIE 3', '10'],
        ['Activities as decided by course faculty', '20'],
        ['SEE', '50'],
        ['Total', '100'],
    ]
    
    theory_table = Table(theory_eval_data, colWidths=[4.0*inch, 1.5*inch])
    theory_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#D3D3D3")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('FONTNAME', (0, 1), (-1, -1), 'Times-Roman'),
    ]))
    elements.append(theory_table)
    elements.append(Spacer(1, 0.2*inch))

    elements.append(Paragraph(
        "<b>SCHEME OF EVALUATION (LABORATORY COURSES)</b>",
        ParagraphStyle('LabEvalTitle', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.12*inch))

    lab_eval_data = [
        ['Assessment', 'Marks'],
        ['Continuous Evaluation in every lab session by the Course Coordinator', '10'],
        ['Record Writing', '20'],
        ['SEE', '50'],
        ['Total', '100'],
    ]
    
    lab_table = Table(lab_eval_data, colWidths=[4.0*inch, 1.5*inch])
    lab_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#D3D3D3")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('FONTNAME', (0, 1), (-1, -1), 'Times-Roman'),
    ]))
    elements.append(lab_table)
    elements.append(Spacer(1, 0.2*inch))

    elements.append(Paragraph(
        "<b>EXAMINATION DETAILS</b>",
        ParagraphStyle('ExamTitle', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.1*inch))

    exam_data = [
        ['Examination', 'Maximum Marks', 'Minimum marks to qualify'],
        ['CIE', '50', '20'],
        ['SEE', '50', '20'],
    ]
    
    exam_table = Table(exam_data, colWidths=[1.5*inch, 1.5*inch, 2.5*inch])
    exam_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#D3D3D3")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('FONTNAME', (0, 1), (-1, -1), 'Times-Roman'),
    ]))
    elements.append(exam_table)

    elements.append(PageBreak())

    # ===== PAGE 6: COURSE TYPES =====
    elements.append(Paragraph(
        "<b>COURSE TYPES</b>",
        ParagraphStyle('CourseTypesTitle', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, fontName='Times-Bold')
    ))
    elements.append(Spacer(1, 0.15*inch))

    course_types_data = [
        ['Basic Science Course', 'BSC'],
        ['Engineering Science Course', 'ESC'],
        ['Emerging Technology Course', 'ETC'],
        ['Programming Language Course', 'PLC'],
        ['Professional Core Course', 'PCC'],
        ['Integrated Professional Core Course', 'IPCC'],
        ['Professional Core Course Laboratory', 'PCCL'],
        ['Professional Elective Course', 'PEC'],
        ['Open Elective Course', 'OEC'],
        ['Project/Mini Project/Internship', 'PI'],
        ['Humanities and Social Sciences, Management Course', 'HSMC'],
        ['Ability Enhancement Course', 'AEC'],
        ['Skill Enhancement Course', 'SEC'],
        ['Universal Human Value Course', 'UHV'],
        ['Non-credit Mandatory Course', 'MC'],
    ]

    ct_table_data = [['Course Type', 'Abbreviation']]
    ct_table_data.extend(course_types_data)
    
    ct_table = Table(ct_table_data, colWidths=[4.2*inch, 1.3*inch])
    ct_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#8ADBE9")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F2F2')]),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('FONTSIZE', (0, 1), (-1, -1), 7.5),
        ('FONTNAME', (0, 1), (-1, -1), 'Times-Roman'),
    ]))
    elements.append(ct_table)
    elements.append(PageBreak())

    # ===== PAGE 7+: SCHEME TABLE =====
    if branch:
        elements.append(Paragraph(
            f"<b>{branch.name.upper()} — SEMESTER {semester} — {year}</b>",
            ParagraphStyle('SchemeTableTitle', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, fontName='Times-Bold', textColor=colors.HexColor('#008000'))
        ))
        elements.append(Spacer(1, 0.12*inch))

        if main_rows:
            header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=6, alignment=TA_CENTER, fontName='Helvetica-Bold', leading=7)
            data_style = ParagraphStyle('Data', parent=styles['Normal'], fontSize=6, alignment=TA_CENTER, leading=7, fontName='Times-Roman')
            title_style = ParagraphStyle('Title', parent=styles['Normal'], fontSize=6, alignment=TA_LEFT, leading=7, fontName='Times-Roman')

            table_data = [[
                Paragraph('Sl. No', header_style),
                Paragraph('Course<br/>Category', header_style),
                Paragraph('Course<br/>Code', header_style),
                Paragraph('Course Title', header_style),
                Paragraph('L', header_style),
                Paragraph('T', header_style),
                Paragraph('P', header_style),
                Paragraph('Total', header_style),
                Paragraph('CIE', header_style),
                Paragraph('SEE', header_style),
                Paragraph('Total', header_style),
                Paragraph('Credits', header_style),
                Paragraph('Assign<br/>Faculty', header_style),
            ]]

            row_num = 1
            for row in main_rows:
                l = int(row.get('l') or 0)
                t = int(row.get('t') or 0)
                p = int(row.get('p') or 0)
                cie = int(row.get('cie') or 0)
                see = int(row.get('see') or 0)
                total_hours = l + t + p
                total_marks = cie + see
                
                table_data.append([
                    Paragraph(str(row_num), data_style),
                    Paragraph(row.get('category', ''), data_style),
                    Paragraph(row.get('code', ''), data_style),
                    Paragraph(row.get('title', ''), title_style),
                    Paragraph(str(l), data_style),
                    Paragraph(str(t), data_style),
                    Paragraph(str(p), data_style),
                    Paragraph(str(total_hours), data_style),
                    Paragraph(str(cie), data_style),
                    Paragraph(str(see), data_style),
                    Paragraph(str(total_marks), data_style),
                    Paragraph(str(row.get('credits', '')), data_style),
                    Paragraph(row.get('faculty_name', ''), data_style),
                ])
                row_num += 1

            col_widths = [0.35*inch, 0.6*inch, 0.65*inch, 1.8*inch, 0.35*inch, 0.35*inch, 0.35*inch, 0.45*inch, 0.35*inch, 0.35*inch, 0.45*inch, 0.45*inch, 0.65*inch]
            scheme_table = Table(table_data, colWidths=col_widths)
            scheme_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#8ADBE9")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F2F2')]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 1), (-1, -1), 'Times-Roman'),
            ]))
            elements.append(scheme_table)
            elements.append(Spacer(1, 0.15*inch))

        # Electives
        if elective_rows:
            elements.append(Paragraph(
                "<b>Elective/Enhancement Courses</b>",
                ParagraphStyle('ElectiveTitle', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, fontName='Times-Bold')
            ))
            elements.append(Spacer(1, 0.1*inch))

            elective_sections = {}
            for row in elective_rows:
                section = row.get('section', 'ESC')
                if section not in elective_sections:
                    elective_sections[section] = []
                elective_sections[section].append(row)

            for section in ['PEC', 'OEC', 'ESC', 'AEC']:
                if section in elective_sections:
                    section_name = {
                        'PEC': 'Professional Elective Course (PEC)',
                        'OEC': 'Open Elective Course (OEC)',
                        'ESC': 'Engineering Science Course (ESC)',
                        'AEC': 'Ability Enhancement Course (AEC)'
                    }[section]
                    
                    elements.append(Paragraph(
                        f"<b>{section_name}</b>",
                        ParagraphStyle('ElectiveSection', parent=styles['Normal'], fontSize=8, alignment=TA_LEFT, fontName='Times-Bold')
                    ))
                    elements.append(Spacer(1, 0.07*inch))

                    elec_header_style = ParagraphStyle('EH', parent=styles['Normal'], fontSize=6.5, alignment=TA_CENTER, fontName='Helvetica-Bold')
                    elec_data_style = ParagraphStyle('ED', parent=styles['Normal'], fontSize=6, alignment=TA_LEFT, fontName='Times-Roman')

                    elec_table_data = [[Paragraph('Course Code', elec_header_style), Paragraph('Course Title', elec_header_style), Paragraph('Assign Faculty', elec_header_style)]]
                    for course in elective_sections[section]:
                        elec_table_data.append([
                            Paragraph(course.get('code', ''), elec_data_style),
                            Paragraph(course.get('title', ''), elec_data_style),
                            Paragraph(course.get('faculty_name', ''), elec_data_style),
                        ])

                    elec_table = Table(elec_table_data, colWidths=[0.9*inch, 3.2*inch, 1.4*inch])
                    elec_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#D9E1F2")),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9F9F9')]),
                        ('FONTSIZE', (0, 0), (-1, -1), 6),
                        ('FONTNAME', (0, 0), (-1, -1), 'Times-Roman'),
                    ]))
                    elements.append(elec_table)
                    elements.append(Spacer(1, 0.1*inch))

    elements.append(Spacer(1, 0.15*inch))
    elements.append(Paragraph(
        f"Generated on {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}",
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=7, alignment=TA_CENTER, fontName='Times-Italic')
    ))

    # Build PDF with BorderedPageCanvas
    doc.build(elements, canvasmaker=BorderedPageCanvas)
    buffer.seek(0)
    return buffer.getvalue()

@login_required
def create_scheme_quick(request, branch_pk, year, semester):
    """Quick generate scheme - creates and returns PDF without form submission."""
    try:
        branch = get_object_or_404(apps.get_model('academics', 'Branch'), pk=branch_pk)
    except Exception:
        messages.error(request, "Branch not found.")
        return redirect('hod:dashboard_redirect')
    
    try:
        main_rows, elective_rows = _fetch_db_rows_for_scheme(branch, int(year), int(semester))
        pdf_bytes = _build_complete_scheme_pdf(branch, int(year), int(semester),
                                               main_rows=main_rows,
                                               elective_rows=elective_rows)
        
        if not pdf_bytes:
            messages.error(request, "Failed to generate PDF.")
            return redirect('hod:dashboard_self', branch_pk=branch_pk)
        
        filename = f"Scheme_{branch.name.replace(' ','_')}_{year}_Sem{semester}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        logger.exception("Error in create_scheme_quick: %s", e)
        messages.error(request, "Error generating scheme PDF.")
        return redirect('hod:dashboard_self', branch_pk=branch_pk)


# --- Paste inside hod/views.py in faculty_assignment_detail (replace the problematic parts) ---
from django.db import transaction
# --- lazy model imports: prevents ImportError if a model was renamed/removed ---
from django.apps import apps

def _get_hod_model(name):
    try:
        return apps.get_model('hod', name)
    except LookupError:
        return None

SchemeCourse = _get_hod_model('SchemeCourse')
Scheme = _get_hod_model('Scheme')              # may be None if model was renamed/removed
CourseAllocation = _get_hod_model('CourseAllocation')
FacultyAssignment = _get_hod_model('FacultyAssignment')
HODAssignment = _get_hod_model('HODAssignment')
# ---------------------------------------------------------------------------

# paste into hod/views.py (overwrite existing faculty_assignments_detail)
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.core.exceptions import FieldError

from .models import HODAssignment, CourseAllocation, FacultyAssignment, SchemeCourse
from academics.models import Branch

@login_required
def faculty_assignments_detail(request, branch_pk):
    """
    Show assigned faculty for a branch, filtered by ?year=&semester=.
    Fallback behaviour: if year/semester selected but no SchemeCourse rows exist,
    show the HOD's CourseAllocation rows (so assignments remain visible).
    """
    branch = get_object_or_404(Branch, pk=branch_pk)

    # parse query params (support multiple param names)
    year_raw = request.GET.get('year') or request.GET.get('academic_year')
    sem_raw = request.GET.get('semester') or request.GET.get('sem')

    try:
        year = int(year_raw) if year_raw not in (None, '', 'None') else None
    except Exception:
        year = None
    try:
        semester = int(sem_raw) if sem_raw not in (None, '', 'None') else None
    except Exception:
        semester = None

    # find HODAssignment for this branch if present
    try:
        hod_assignment = HODAssignment.objects.get(branch=branch)
    except HODAssignment.DoesNotExist:
        hod_assignment = None

    # Build scheme_qs defensively
    scheme_qs = SchemeCourse.objects.all().select_related('scheme')

    # Try to restrict scheme_qs to this branch via several likely lookups.
    branch_lookups = ['scheme__branch', 'scheme__branch_id', 'scheme__branch__pk']
    filtered_by_branch = False
    for lk in branch_lookups:
        try:
            scheme_qs = scheme_qs.filter(**{lk: branch})
            filtered_by_branch = True
            break
        except (FieldError, ValueError):
            scheme_qs = SchemeCourse.objects.all().select_related('scheme')

    # If user provided year, try common year lookups
    if year is not None:
        year_lookups = ['scheme__year', 'scheme__academic_year', 'year', 'academic_year', 'scheme__admission_year']
        matched_year = False
        for lk in year_lookups:
            try:
                temp_qs = scheme_qs.filter(**{lk: year})
                scheme_qs = temp_qs
                matched_year = True
                break
            except (FieldError, ValueError):
                continue
        if not matched_year:
            scheme_qs = SchemeCourse.objects.none()

    # If user provided semester, try common semester lookups
    if semester is not None and scheme_qs.exists():
        sem_lookups = ['semester', 'scheme__semester', 'scheme__sem', 'term']
        matched_sem = False
        for lk in sem_lookups:
            try:
                temp_qs = scheme_qs.filter(**{lk: semester})
                scheme_qs = temp_qs
                matched_sem = True
                break
            except (FieldError, ValueError):
                continue
        if not matched_sem:
            # if year/semester requested but semester couldn't be matched, set to empty
            if year is not None or semester is not None:
                scheme_qs = SchemeCourse.objects.none()

    # Collect course codes from scheme rows (these identify the courses for that branch/year/sem)
    scheme_codes = list(scheme_qs.values_list('course_code', flat=True).distinct())

    # If we have no scheme_codes but user selected year/semester, decide fallback behaviour.
    # Set fallback_to_allocations = True to show HOD allocations when no scheme rows found.
    fallback_to_allocations = True

    if (year is not None or semester is not None) and not scheme_codes:
        if fallback_to_allocations:
            # Show allocations for the HOD (if present) or none
            if hod_assignment:
                course_alloc_qs = CourseAllocation.objects.filter(hod_assignment=hod_assignment)
            else:
                course_alloc_qs = CourseAllocation.objects.none()
        else:
            course_alloc_qs = CourseAllocation.objects.none()
    else:
        # Normal flow: use scheme_codes (if present) or show allocations for HOD when no filters applied
        if hod_assignment:
            if scheme_codes:
                course_alloc_qs = CourseAllocation.objects.filter(hod_assignment=hod_assignment, course_code__in=scheme_codes)
            else:
                course_alloc_qs = CourseAllocation.objects.filter(hod_assignment=hod_assignment)
        else:
            if scheme_codes:
                course_alloc_qs = CourseAllocation.objects.filter(course_code__in=scheme_codes)
            else:
                course_alloc_qs = CourseAllocation.objects.none()

    # Prefetch latest faculty assignments for each course allocation
    fa_prefetch = Prefetch(
        'facultyassignment_set',
        queryset=FacultyAssignment.objects.select_related('faculty').order_by('assigned_on'),
        to_attr='fa_list'
    )
    course_alloc_qs = course_alloc_qs.prefetch_related(fa_prefetch)

    assignments = []
    for ca in course_alloc_qs:
        fa_obj = (getattr(ca, 'fa_list', [])[-1]) if getattr(ca, 'fa_list', []) else None
        assigned_faculty_name = None
        assigned_on = None
        if fa_obj:
            assigned_on = fa_obj.assigned_on
            faculty_profile = fa_obj.faculty
            user = getattr(faculty_profile, 'user', None)
            if user:
                assigned_faculty_name = user.get_full_name() or user.username or getattr(user, 'email', '')
            else:
                assigned_faculty_name = getattr(faculty_profile, 'display_name', None) or str(faculty_profile)

        assignments.append({
            'course_code': ca.course_code,
            'course_title': getattr(ca, 'course_title', '') or '',
            'credits': getattr(ca, 'credits', None),
            'assigned_faculty_name': assigned_faculty_name,
            'assigned_on': assigned_on,
            'course_allocation_id': ca.id,
        })

    assignments = sorted(assignments, key=lambda x: x['course_code'])

    context = {
        'branch': branch,
        'year': year,
        'semester': semester,
        'assignments': assignments,
        'hod_assignment': hod_assignment,
    }
    return render(request, 'hod/faculty_assignments_detail.html', context)


# optional legacy view for hod_assignment id if you used it elsewhere
@login_required
def faculty_assignments_detail_by_hod(request, hod_assignment_id):
    try:
        hod_assignment = HODAssignment.objects.get(pk=hod_assignment_id)
    except HODAssignment.DoesNotExist:
        return redirect('hod:dashboard_redirect')
    return faculty_assignments_detail(request, branch_pk=hod_assignment.branch.pk)


@login_required
def manage_schemes(request, branch_pk):
    """Manage all schemes for a branch."""
    try:
        # Get the branch object first
        Branch = apps.get_model('academics', 'Branch')
        branch = get_object_or_404(Branch, pk=branch_pk)
        
        # Now get SchemeDocument model
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        
        # Get filter parameters
        year = request.GET.get('year', '').strip()
        semester = request.GET.get('semester', '').strip()
        
        # Build base queryset
        active_schemes = SchemeDocument.objects.filter(
            branch=branch,
            is_deleted=False
        )
        
        # Apply year filter if provided
        if year:
            try:
                active_schemes = active_schemes.filter(year=int(year))
            except ValueError:
                pass
        
        # Apply semester filter if provided
        if semester:
            try:
                active_schemes = active_schemes.filter(semester=int(semester))
            except ValueError:
                pass
        
        active_schemes = active_schemes.order_by('-created_at')
        
        # Get deleted schemes (for recycle bin)
        deleted_schemes = SchemeDocument.objects.filter(
            branch=branch,
            is_deleted=True
        ).order_by('-created_at')
        
        # Get list of available semesters for filter dropdown
        semesters = [1, 2, 3, 4, 5, 6, 7, 8]
        
        context = {
            'branch': branch,
            'schemes': active_schemes,
            'active_schemes': active_schemes,
            'deleted_schemes': deleted_schemes,
            'semesters': semesters,
        }
        return render(request, 'hod/manage_schemes.html', context)
    except LookupError as e:
        logger.exception("Model not found: %s", e)
        messages.error(request, "Required models not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error managing schemes: %s", e)
        messages.error(request, f"Failed to load schemes: {e}")
        return redirect('hod:dashboard_redirect')

@login_required
def view_scheme(request, scheme_pk):
    """View a scheme document."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_pk)
        
        context = {
            'scheme': scheme,
            'branch': scheme.branch,
            'year': scheme.year,
            'semester': scheme.semester,
        }
        return render(request, 'hod/view_scheme.html', context)
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error viewing scheme: %s", e)
        messages.error(request, "Failed to load scheme.")
        return redirect('hod:dashboard_redirect')


@login_required
def download_scheme(request, scheme_pk):
    """Download scheme PDF."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_pk)
        
        if not scheme.pdf_file:
            messages.error(request, "PDF file not found.")
            return redirect('hod:manage_schemes', branch_pk=scheme.branch.pk)
        
        return FileResponse(
            scheme.pdf_file.open('rb'),
            content_type='application/pdf',
            as_attachment=True,
            filename=scheme.pdf_file.name.split('/')[-1]
        )
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error downloading scheme: %s", e)
        messages.error(request, "Failed to download scheme.")
        return redirect('hod:dashboard_redirect')


@login_required
def edit_scheme(request, scheme_pk):
    """Edit a scheme document."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_pk)
        
        branch = scheme.branch
        year = scheme.year
        semester = scheme.semester
        
        # Fetch existing scheme data
        main_rows = []
        elective_rows = []
        
        try:
            SchemeCourse = apps.get_model('hod', 'SchemeCourse')
            
            # Get main courses
            main_courses = SchemeCourse.objects.filter(
                branch=branch,
                year=year,
                semester=semester,
                is_elective=False
            ).select_related('faculty')
            
            for sc in main_courses:
                faculty_name = ''
                if sc.faculty:
                    faculty_name = sc.faculty.get_full_name() or sc.faculty.username
                
                main_rows.append({
                    'id': sc.id,
                    'category': getattr(sc, 'category', '') or '',
                    'code': sc.course_code,
                    'title': getattr(sc, 'course_title', '') or '',
                    'l': int(getattr(sc, 'l', 0) or 0),
                    't': int(getattr(sc, 't', 0) or 0),
                    'p': int(getattr(sc, 'p', 0) or 0),
                    'cie': int(getattr(sc, 'cie', 0) or 0),
                    'see': int(getattr(sc, 'see', 0) or 0),
                    'credits': str(getattr(sc, 'credits', 0) or 0),
                    'faculty_id': sc.faculty.id if sc.faculty else None,
                    'faculty_name': faculty_name,
                })
            
            # Get elective courses
            elective_courses = SchemeCourse.objects.filter(
                branch=branch,
                year=year,
                semester=semester,
                is_elective=True
            ).select_related('faculty')
            
            for sc in elective_courses:
                faculty_name = ''
                if sc.faculty:
                    faculty_name = sc.faculty.get_full_name() or sc.faculty.username
                
                elective_rows.append({
                    'id': sc.id,
                    'section': getattr(sc, 'category', 'ESC') or 'ESC',
                    'code': sc.course_code,
                    'title': getattr(sc, 'course_title', '') or '',
                    'faculty_id': sc.faculty.id if sc.faculty else None,
                    'faculty_name': faculty_name,
                })
        except LookupError:
            logger.debug("SchemeCourse model not found")
        
        faculty_list = CustomUser.objects.filter(role='faculty', is_active=True)
        
        context = {
            'scheme': scheme,
            'branch': branch,
            'year': year,
            'semester': semester,
            'main_rows': main_rows,
            'elective_rows': elective_rows,
            'faculty_list': faculty_list,
        }
        return render(request, 'hod/edit_scheme.html', context)
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error editing scheme: %s", e)
        messages.error(request, "Failed to load scheme for editing.")
        return redirect('hod:dashboard_redirect')


@login_required
def trash_scheme(request, scheme_pk):
    """Move scheme to trash (soft delete)."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_pk)
        
        scheme.is_deleted = True
        scheme.save()
        
        messages.success(request, f"Scheme '{scheme.title}' moved to trash.")
        return redirect('hod:manage_schemes', branch_pk=scheme.branch.pk)
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error trashing scheme: %s", e)
        messages.error(request, "Failed to move scheme to trash.")
        return redirect('hod:dashboard_redirect')


@login_required
def restore_scheme(request, scheme_pk):
    """Restore a trashed scheme."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_pk)
        
        scheme.is_deleted = False
        scheme.save()
        
        messages.success(request, f"Scheme '{scheme.title}' restored.")
        return redirect('hod:manage_schemes', branch_pk=scheme.branch.pk)
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error restoring scheme: %s", e)
        messages.error(request, "Failed to restore scheme.")
        return redirect('hod:dashboard_redirect')


@login_required
def permanent_delete_scheme(request, scheme_pk):
    """Permanently delete a scheme."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_pk)
        
        branch_pk = scheme.branch.pk
        scheme.delete()
        
        messages.success(request, "Scheme permanently deleted.")
        return redirect('hod:manage_schemes', branch_pk=branch_pk)
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error permanently deleting scheme: %s", e)
        messages.error(request, "Failed to permanently delete scheme.")
        return redirect('hod:dashboard_redirect')


@login_required
def regenerate_scheme(request, scheme_id):
    """Regenerate a scheme PDF."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_id)
        
        branch = scheme.branch
        year = scheme.year
        semester = scheme.semester
        
        # Regenerate PDF
        pdf_bytes = _build_complete_scheme_pdf(branch, year, semester)
        
        # Save to scheme
        filename = f"Scheme_{branch.code}_{year}_Sem{semester}.pdf"
        scheme.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)
        
        messages.success(request, "Scheme PDF regenerated successfully.")
        return redirect('hod:manage_schemes', branch_pk=scheme.pk)
    except LookupError:
        messages.error(request, "Model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error regenerating scheme: %s", e)
        messages.error(request, "Failed to regenerate scheme.")
        return redirect('hod:dashboard_redirect')


@login_required
def edit_assignment(request, assignment_id):
    """Edit a faculty assignment."""
    try:
        assignment = get_object_or_404(FacultyAssignment, pk=assignment_id)
        
        if request.method == 'POST':
            assignment.save()
            messages.success(request, "Assignment updated successfully.")
            return redirect('hod:faculty_assignment_history')
        
        context = {'assignment': assignment}
        return render(request, 'hod/edit_assignment.html', context)
    except Exception as e:
        logger.exception("Error editing assignment: %s", e)
        messages.error(request, "Failed to edit assignment.")
        return redirect('hod:faculty_assignment_history')


@login_required
def remove_assignment(request, assignment_id):
    """Remove a faculty assignment."""
    try:
        assignment = get_object_or_404(FacultyAssignment, pk=assignment_id)
        assignment.delete()
        messages.success(request, "Assignment removed successfully.")
        return redirect('hod:faculty_assignment_history')
    except Exception as e:
        logger.exception("Error removing assignment: %s", e)
        messages.error(request, "Failed to remove assignment.")
        return redirect('hod:faculty_assignment_history')


@login_required
def activity_history(request):
    """View activity history."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        activities = SchemeDocument.objects.all().order_by('-created_at')[:100]
        context = {'activities': activities}
        return render(request, 'hod/activity_history.html', context)
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error fetching activity history: %s", e)
        messages.error(request, "Failed to load activity history.")
        return redirect('hod:dashboard_redirect')


@login_required
def download_scheme_pdf(request, activity_id):
    """Download scheme PDF from activity history."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=activity_id)
        
        if not scheme.pdf_file:
            messages.error(request, "PDF file not found.")
            return redirect('hod:activity_history')
        
        return FileResponse(
            scheme.pdf_file.open('rb'),
            content_type='application/pdf',
            as_attachment=True,
            filename=f"Scheme_{scheme.year}_{scheme.semester}.pdf"
        )
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error downloading scheme PDF: %s", e)
        messages.error(request, "Failed to download PDF.")
        return redirect('hod:activity_history')
@login_required
def view_scheme(request, scheme_pk):
    """View a scheme document."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_pk)
        
        if not scheme.pdf_file:
            messages.error(request, "PDF file not found for this scheme.")
            return redirect('hod:manage_schemes', branch_pk=scheme.branch.pk)
        
        # Return PDF directly in browser
        return FileResponse(
            scheme.pdf_file.open('rb'),
            content_type='application/pdf',
            filename=scheme.pdf_file.name.split('/')[-1]
        )
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error viewing scheme: %s", e)
        messages.error(request, f"Failed to load scheme: {str(e)}")
        return redirect('hod:manage_schemes', branch_pk=scheme.branch.pk if 'scheme' in locals() else 1)


@login_required
def edit_scheme(request, scheme_pk):
    """Edit a scheme document - redirect to create_scheme form."""
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme = get_object_or_404(SchemeDocument, pk=scheme_pk)
        
        branch = scheme.branch
        year = scheme.year
        semester = scheme.semester
        
        # Redirect to create_scheme form with the scheme's details pre-filled
        # The form will allow editing and re-saving
        return redirect('hod:create_scheme', branch_pk=branch.pk, year=year, semester=semester)
    except LookupError:
        messages.error(request, "SchemeDocument model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error editing scheme: %s", e)
        messages.error(request, f"Failed to edit scheme: {str(e)}")
        return redirect('hod:manage_schemes', branch_pk=1)

@login_required
def save_scheme_courses(request, branch_pk, year, semester):
    """Save scheme courses from form submission."""
    if request.method == 'POST':
        try:
            Branch = apps.get_model('academics', 'Branch')
            branch = get_object_or_404(Branch, pk=branch_pk)
            
            SchemeCourse = apps.get_model('hod', 'SchemeCourse')
            
            # SAFELY delete existing SchemeCourse rows and related CourseAllocation/FacultyAssignment for this HOD
            try:
                CourseAllocation = apps.get_model('hod', 'CourseAllocation')
                FacultyAssignment = apps.get_model('hod', 'FacultyAssignment')
                HODAssignment = apps.get_model('hod', 'HODAssignment')

                old_qs = SchemeCourse.objects.filter(branch=branch, year=year, semester=semester)
                old_codes = list(old_qs.values_list('course_code', flat=True))

                # delete SchemeCourse rows
                old_qs.delete()

                # if we have a hod record, delete CourseAllocation & FacultyAssignment for that hod and those codes
                hod_obj = getattr(request.user, 'hod_assignment', None)
                if hod_obj and old_codes:
                    # delete faculty assignments referencing allocations for this hod
                    allocations = CourseAllocation.objects.filter(hod_assignment=hod_obj, course_code__in=old_codes)
                    if allocations.exists():
                        FacultyAssignment.objects.filter(course_allocation__in=allocations).delete()
                        allocations.delete()
            except Exception:
                logger.exception("Error while cleaning up old scheme rows and allocations in save_scheme_courses")
            
            # Save main courses from form
            main_row_count = int(request.POST.get('main_row_count', 0))
            for i in range(main_row_count):
                course_code = request.POST.get(f'main_code_{i}', '').strip()
                if not course_code:
                    continue
                
                course_title = request.POST.get(f'main_title_{i}', '')
                faculty_id = request.POST.get(f'main_faculty_{i}', None)
                
                faculty = None
                if faculty_id:
                    try:
                        faculty = CustomUser.objects.get(id=faculty_id, role='faculty')
                    except CustomUser.DoesNotExist:
                        pass
                
                SchemeCourse.objects.create(
                    branch=branch,
                    year=year,
                    semester=semester,
                    course_code=course_code,
                    course_title=course_title,
                    faculty=faculty,
                    is_elective=False,
                    l=int(request.POST.get(f'main_l_{i}', 0) or 0),
                    t=int(request.POST.get(f'main_t_{i}', 0) or 0),
                    p=int(request.POST.get(f'main_p_{i}', 0) or 0),
                    cie=int(request.POST.get(f'main_cie_{i}', 0) or 0),
                    see=int(request.POST.get(f'main_see_{i}', 0) or 0),
                    credits=float(request.POST.get(f'main_credits_{i}', 0) or 0),
                )
            
            # Save elective courses
            elective_row_count = int(request.POST.get('elective_row_count', 0))
            for i in range(elective_row_count):
                course_code = request.POST.get(f'elective_code_{i}', '').strip()
                if not course_code:
                    continue
                
                course_title = request.POST.get(f'elective_title_{i}', '')
                faculty_id = request.POST.get(f'elective_faculty_{i}', None)
                
                faculty = None
                if faculty_id:
                    try:
                        faculty = CustomUser.objects.get(id=faculty_id, role='faculty')
                    except CustomUser.DoesNotExist:
                        pass
                
                SchemeCourse.objects.create(
                    branch=branch,
                    year=year,
                    semester=semester,
                    course_code=course_code,
                    course_title=course_title,
                    faculty=faculty,
                    is_elective=True,
                    category='ESC',
                )
            
            messages.success(request, "Scheme courses saved successfully!")
            logger.info(f"Saved scheme courses for {branch.name} Y{year} S{semester}")
            
            # Redirect based on button clicked
            if 'save_download' in request.POST:
                return redirect('hod:generate_pdf', branch_pk=branch_pk, year=year, semester=semester)
            else:
                return redirect('hod:manage_schemes', branch_pk=branch_pk)
                
        except Exception as e:
            logger.exception(f"Error saving scheme courses: {e}")
            messages.error(request, f"Failed to save courses: {str(e)}")
            return redirect('hod:create_scheme', branch_pk=branch_pk, year=year, semester=semester)
    
    return redirect('hod:create_scheme', branch_pk=branch_pk, year=year, semester=semester)

# Add / ensure these imports are present at top of hod/views.py
import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

# local models - adjust names if your project uses different class names
from users.models import CustomUser

# academics models may be named differently in your project.
# I try to import commonly used names and fall back to None if not present.
try:
    # In your project you used `CollegeLevelCourse` earlier in screenshots.
    from academics.models import CollegeLevelCourse as DeanCourse, Branch
except Exception:
    try:
        # fallback name
        from academics.models import Course as DeanCourse, Branch
    except Exception:
        DeanCourse = None
        Branch = None

# HOD app models
from .models import SchemeCourse, Faculty, FacultyAssignment, CourseAllocation, HODAssignment

logger = logging.getLogger(__name__)


@login_required
def create_scheme(request, branch_pk, year, semester):
    """
    HOD: show scheme form (GET) and save submitted scheme rows (POST).
    When HOD saves rows this ensures CourseAllocation and FacultyAssignment objects
    are created/updated for the HOD (linked via HODAssignment).
    """
    branch = get_object_or_404(Branch, pk=branch_pk)
    faculty_list = CustomUser.objects.filter(role='faculty', is_active=True)

    # Build Dean course list (display only) using whatever DeanCourse is available
    dean_courses = []
    if DeanCourse is not None:
        try:
            dean_qs = DeanCourse.objects.filter(Q(branch__isnull=True) | Q(branch=branch))
            if hasattr(DeanCourse, 'semester'):
                try:
                    dean_qs = dean_qs.filter(semester=semester)
                except Exception:
                    pass
        except Exception:
            dean_qs = DeanCourse.objects.none()

        for c in dean_qs:
            try:
                f_id = None
                if hasattr(c, 'faculty_id') and getattr(c, 'faculty_id') not in (None, ''):
                    try:
                        f_id = int(getattr(c, 'faculty_id'))
                    except Exception:
                        f_obj = getattr(c, 'faculty', None)
                        f_id = int(getattr(f_obj, 'id')) if f_obj else None
                dean_courses.append({
                    'id': getattr(c, 'id', None),
                    'category': getattr(c, 'course_category', '') or '',
                    'course_code': getattr(c, 'course_code', '') or '',
                    'course_title': getattr(c, 'course_title', '') or '',
                    'l': int(getattr(c, 'teaching_hours_L', 0) or 0),
                    't': int(getattr(c, 'teaching_hours_T', 0) or 0),
                    'p': int(getattr(c, 'teaching_hours_P', 0) or 0),
                    'total_hours': (int(getattr(c, 'teaching_hours_L', 0) or 0)
                                    + int(getattr(c, 'teaching_hours_T', 0) or 0)
                                    + int(getattr(c, 'teaching_hours_P', 0) or 0)),
                    'cie': int(getattr(c, 'cie_marks', 0) or 0),
                    'see': int(getattr(c, 'see_marks', 0) or 0),
                    'total_marks': (int(getattr(c, 'cie_marks', 0) or 0)
                                    + int(getattr(c, 'see_marks', 0) or 0)),
                    'credits': getattr(c, 'credits', 0) or 0,
                    'faculty_id': f_id,
                    'faculty_username': getattr(getattr(c, 'faculty', None), 'username', '') if hasattr(c, 'faculty') else '',
                })
            except Exception:
                # skip problematic dean course rows; don't break form rendering
                logger.exception("Error preparing dean course data for display (course id=%s).", getattr(c, 'id', None))

    # POST: user clicked Save Scheme / Save & Download
    if request.method == 'POST':
        # handle cancel/back buttons
        if 'cancel' in request.POST or 'back' in request.POST:
            dashboard_url = reverse('hod:dashboard_self', args=[branch_pk])
            return redirect(f"{dashboard_url}?year={year}&semester={semester}")

        # clear any previous messages
        list(messages.get_messages(request))

        created_count = 0
        hod_assignment = getattr(request.user, 'hod_assignment', None)

        # MAIN rows loop: index 1..N with form names like code_new_1, title_new_1, etc.
        i = 1
        while True:
            code = (request.POST.get(f'code_new_{i}', '') or '').strip()
            title = (request.POST.get(f'title_new_{i}', '') or '').strip()
            if not code and not title:
                break

            # numeric fields (safe parsing)
            l = request.POST.get(f'l_new_{i}') or 0
            t = request.POST.get(f't_new_{i}') or 0
            p = request.POST.get(f'p_new_{i}') or 0
            try:
                total_hours = int(request.POST.get(f'total_hours_new_{i}') or (int(l or 0) + int(t or 0) + int(p or 0)))
            except Exception:
                total_hours = int((int(l or 0) + int(t or 0) + int(p or 0)))
            cie = request.POST.get(f'cie_new_{i}') or 0
            see = request.POST.get(f'see_new_{i}') or 0
            try:
                total_marks = int(request.POST.get(f'total_marks_new_{i}') or (int(cie or 0) + int(see or 0)))
            except Exception:
                total_marks = int((int(cie or 0) + int(see or 0)))
            credits = request.POST.get(f'credits_new_{i}') or 0
            faculty_id = request.POST.get(f'faculty_new_{i}') or None
            category = request.POST.get(f'category_new_{i}') or None

            try:
                with transaction.atomic():
                    # Try to create SchemeCourse with the richer set of fields (works if model has them)
                    sc = None
                    try:
                        sc = SchemeCourse.objects.create(
                            branch=branch_pk,
                            year=int(year),
                            semester=int(semester),
                            course_code=code,
                            # some projects don't have course_title field; guard with hasattr
                            **({'course_title': title} if hasattr(SchemeCourse, 'course_title') else {}),
                            **({'l': int(l or 0)} if hasattr(SchemeCourse, 'l') else {}),
                            **({'t': int(t or 0)} if hasattr(SchemeCourse, 't') else {}),
                            **({'p': int(p or 0)} if hasattr(SchemeCourse, 'p') else {}),
                            **({'total_hours': int(total_hours or 0)} if hasattr(SchemeCourse, 'total_hours') else {}),
                            **({'cie': int(cie or 0)} if hasattr(SchemeCourse, 'cie') else {}),
                            **({'see': int(see or 0)} if hasattr(SchemeCourse, 'see') else {}),
                            **({'total_marks': int(total_marks or 0)} if hasattr(SchemeCourse, 'total_marks') else {}),
                            **({'credits': float(credits or 0)} if hasattr(SchemeCourse, 'credits') else {}),
                            **({'category': category} if hasattr(SchemeCourse, 'category') else {}),
                            **({'is_elective': False} if hasattr(SchemeCourse, 'is_elective') else {}),
                        )
                    except Exception:
                        # fallback: create minimal SchemeCourse row (only fields that must exist)
                        sc_kwargs = {'course_code': code, 'semester': semester}
                        # attempt to attach to a Scheme object if your model requires that; skip if not present
                        try:
                            sc = SchemeCourse.objects.create(**sc_kwargs)
                        except Exception:
                            # if minimal creation fails, raise so transaction rolls back and we log
                            raise

                    # Ensure CourseAllocation exists for this HOD
                    course_alloc = None
                    if hod_assignment:
                        course_alloc, ca_created = CourseAllocation.objects.get_or_create(
                            hod_assignment=hod_assignment,
                            course_code=code,
                            defaults={
                                'course_title': title or '',
                                'course_category': category or '',
                                'teaching_hours_L': int(l or 0),
                                'teaching_hours_T': int(t or 0),
                                'teaching_hours_P': int(p or 0),
                                'credits': float(credits or 0),
                            }
                        )
                        if not ca_created:
                            # update basic hours/credits if they changed
                            changed = False
                            if hasattr(course_alloc, 'teaching_hours_L') and course_alloc.teaching_hours_L != int(l or 0):
                                course_alloc.teaching_hours_L = int(l or 0); changed = True
                            if hasattr(course_alloc, 'teaching_hours_T') and course_alloc.teaching_hours_T != int(t or 0):
                                course_alloc.teaching_hours_T = int(t or 0); changed = True
                            if hasattr(course_alloc, 'teaching_hours_P') and course_alloc.teaching_hours_P != int(p or 0):
                                course_alloc.teaching_hours_P = int(p or 0); changed = True
                            if hasattr(course_alloc, 'credits') and float(course_alloc.credits or 0) != float(credits or 0):
                                course_alloc.credits = float(credits or 0); changed = True
                            if changed:
                                course_alloc.save()

                    # If faculty chosen, link sc.faculty (if available) and create/update FacultyAssignment
                    if faculty_id:
                        try:
                            faculty_user = CustomUser.objects.get(id=int(faculty_id))
                            faculty_profile, _ = Faculty.objects.get_or_create(
                                user=faculty_user,
                                defaults={'department': getattr(hod_assignment.branch, 'name', '') if hod_assignment else ''}
                            )
                            # attach to scheme row if model supports it
                            try:
                                # If SchemeCourse has a faculty FK field
                                if hasattr(sc, 'faculty'):
                                    sc.faculty = faculty_user
                                    sc.save(update_fields=['faculty'])
                            except Exception:
                                # ignore if scheme model doesn't accept faculty in same way
                                pass

                            # create or update FacultyAssignment linked to CourseAllocation (if course_alloc exists)
                            if course_alloc:
                                fa, fa_created = FacultyAssignment.objects.update_or_create(
                                    course_allocation=course_alloc,
                                    defaults={'faculty': faculty_profile, 'assigned_on': timezone.now()}
                                )
                                logger.info("FacultyAssignment %s for code=%s alloc=%s", 'created' if fa_created else 'updated', code, getattr(course_alloc, 'pk', None))

                        except CustomUser.DoesNotExist:
                            logger.warning("Faculty user not found (id=%s) while saving scheme.", faculty_id)

                    created_count += 1
            except Exception as e:
                # log but continue to next row - transaction ensures partial row not saved
                logger.exception("Failed to save scheme row #%s (code=%s): %s", i, code, e)
            i += 1

        # Elective sections (pec, oec, esc, aec) — same logic, fewer numeric fields
        for section in ['pec', 'oec', 'esc', 'aec']:
            j = 1
            while True:
                code = (request.POST.get(f'{section}_code_{j}', '') or '').strip()
                title = (request.POST.get(f'{section}_title_{j}', '') or '').strip()
                if not code and not title:
                    break
                faculty_id = request.POST.get(f'{section}_faculty_{j}') or None

                try:
                    with transaction.atomic():
                        sc = None
                        try:
                            sc = SchemeCourse.objects.create(
                                branch=branch_pk,
                                year=int(year),
                                semester=int(semester),
                                course_code=code,
                                **({'course_title': title} if hasattr(SchemeCourse, 'course_title') else {}),
                                **({'category': section.upper()} if hasattr(SchemeCourse, 'category') else {}),
                                **({'is_elective': True} if hasattr(SchemeCourse, 'is_elective') else {}),
                            )
                        except Exception:
                            sc = SchemeCourse.objects.create(course_code=code)

                        course_alloc = None
                        if hod_assignment:
                            course_alloc, ca_created = CourseAllocation.objects.get_or_create(
                                hod_assignment=hod_assignment,
                                course_code=code,
                                defaults={
                                    'course_title': title or '',
                                    'course_category': section.upper(),
                                    'teaching_hours_L': 0,
                                    'teaching_hours_T': 0,
                                    'teaching_hours_P': 0,
                                    'credits': 0
                                }
                            )

                        if faculty_id:
                            try:
                                faculty_user = CustomUser.objects.get(id=int(faculty_id))
                                faculty_profile, _ = Faculty.objects.get_or_create(
                                    user=faculty_user,
                                    defaults={'department': getattr(hod_assignment.branch, 'name', '') if hod_assignment else ''}
                                )
                                if hasattr(sc, 'faculty'):
                                    sc.faculty = faculty_user
                                    sc.save(update_fields=['faculty'])
                                if course_alloc:
                                    FacultyAssignment.objects.update_or_create(
                                        course_allocation=course_alloc,
                                        defaults={'faculty': faculty_profile, 'assigned_on': timezone.now()}
                                    )
                            except CustomUser.DoesNotExist:
                                logger.warning("Faculty user id=%s not found for elective %s.", faculty_id, code)

                        created_count += 1
                except Exception as e:
                    logger.exception("Failed to save elective %s row %s: %s", section, j, e)
                j += 1

        # messages & redirect
        if created_count:
            messages.success(request, f"Scheme saved successfully! ({created_count} rows created). CourseAllocation/FacultyAssignment should be created for HOD.")
        else:
            messages.info(request, "No rows were created. Check submitted data.")

        return redirect('hod:create_scheme', branch_pk=branch_pk, year=year, semester=semester)

    # GET -> render template
    context = {
        'branch': branch,
        'year': year,
        'semester': semester,
        'dean_courses': dean_courses,
        'faculty_list': faculty_list,
    }
    return render(request, 'hod/create_scheme.html', context)

# hod/views.py
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.decorators import login_required

@login_required
def approve_faculty_pdf(request, pk):
    if request.method != 'POST':
        return redirect('hod:dashboard_self', pk)  # or appropriate redirect

    from django.apps import apps
    try:
        FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
    except LookupError:
        messages.error(request, "Approve feature unavailable.")
        return redirect('hod:dashboard_self', pk)

    obj = get_object_or_404(FacultySyllabusPDF, pk=pk)
    obj.approved = True
    obj.approved_by = request.user
    obj.approved_at = timezone.now()
    obj.save()
    messages.success(request, "Faculty PDF approved.")
    return redirect(request.META.get('HTTP_REFERER') or 'hod:dashboard_self', pk)

# hod/views.py
from django.http import HttpResponse
from django.contrib import messages
from django.shortcuts import redirect
from io import BytesIO
from django.apps import apps
from django.contrib.auth.decorators import login_required

# --- Pdf merging compatibility shim ---
# Try to import PdfMerger (preferred). If not available, fall back to PdfReader/PdfWriter.
try:
    # Newer pypdf provides PdfMerger
    from pypdf import PdfMerger  # type: ignore

    def merge_pdfs(input_paths, output_stream):
        """
        Merge list of file paths or file-like objects into output_stream using PdfMerger.
        input_paths: iterable of paths or file-like objects
        output_stream: file-like object opened for binary write
        """
        merger = PdfMerger()
        for p in input_paths:
            merger.append(p)
        merger.write(output_stream)
        merger.close()

except Exception:
    # Fallback using PdfReader + PdfWriter (older/different pypdf versions)
    from pypdf import PdfReader, PdfWriter  # type: ignore

    def merge_pdfs(input_paths, output_stream):
        """
        Merge PDFs using PdfReader/PdfWriter.
        input_paths: iterable of paths or file-like objects
        output_stream: file-like object opened for binary write
        """
        writer = PdfWriter()
        for p in input_paths:
            reader = PdfReader(p)
            for page in reader.pages:
                writer.add_page(page)
        writer.write(output_stream)
        # Do not close output_stream here; caller manages it.


@login_required
def generate_combined_syllabus(request, branch_pk):
    """
    POST handler that merges selected scheme PDFs + approved faculty PDFs
    into a single combined syllabus and returns it as a download.
    """
    if request.method != 'POST':
        return redirect('hod:dashboard_self', branch_pk)

    scheme_ids = request.POST.getlist('scheme_pdf_ids')
    faculty_ids = request.POST.getlist('faculty_pdf_ids')

    files_to_merge = []

    # get scheme files (try academics.SchemePDF then hod.SchemeDocument)
    SchemeModel = None
    for candidate in (('academics', 'SchemePDF'), ('hod', 'SchemeDocument')):
        try:
            SchemeModel = apps.get_model(candidate[0], candidate[1])
            break
        except LookupError:
            SchemeModel = None

    if SchemeModel and scheme_ids:
        for pk in scheme_ids:
            try:
                s = SchemeModel.objects.get(pk=pk)
                # prefer file path if available
                if getattr(s, 'pdf_file', None):
                    try:
                        files_to_merge.append(s.pdf_file.path)
                    except Exception:
                        # fallback to file-like object
                        try:
                            files_to_merge.append(s.pdf_file)
                        except Exception:
                            continue
            except Exception:
                continue

    # approved faculty pdfs
    try:
        FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
    except LookupError:
        FacultySyllabusPDF = None

    if FacultySyllabusPDF and faculty_ids:
        for pk in faculty_ids:
            try:
                f = FacultySyllabusPDF.objects.get(pk=pk, approved=True)
                if getattr(f, 'pdf_file', None):
                    try:
                        files_to_merge.append(f.pdf_file.path)
                    except Exception:
                        try:
                            files_to_merge.append(f.pdf_file)
                        except Exception:
                            continue
            except Exception:
                continue

    if not files_to_merge:
        messages.error(request, "No PDFs selected or available to merge.")
        # preserve referer if possible
        referer = request.META.get('HTTP_REFERER')
        if referer:
            return redirect(referer)
        return redirect('hod:dashboard_self', branch_pk)

    # Merge using compatibility helper
    try:
        out = BytesIO()
        merge_pdfs(files_to_merge, out)
        out.seek(0)

        year = request.POST.get('year', '').strip()
        semester = request.POST.get('semester', '').strip()
        filename = f"combined_syllabus_{branch_pk}_{year}_sem{semester}.pdf"

        response = HttpResponse(out.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception:
        messages.error(request, "Failed to merge PDFs. Contact admin.")
        referer = request.META.get('HTTP_REFERER')
        if referer:
            return redirect(referer)
        return redirect('hod:dashboard_self', branch_pk)


@login_required
def create_combined_syllabus(request, branch_pk):
    """
    Render a page where HOD can select which scheme PDFs and approved faculty PDFs
    to include in the combined syllabus PDF.
    """
    Branch = apps.get_model('academics', 'Branch')
    branch = get_object_or_404(Branch, pk=branch_pk)

    year = request.GET.get('year') or request.GET.get('academic_year') or request.POST.get('year', '')
    semester = request.GET.get('semester') or request.POST.get('semester', '')

    # scheme PDFs from hod.SchemeDocument
    scheme_pdfs = []
    try:
        SchemeDoc = apps.get_model('hod', 'SchemeDocument')
        qs = SchemeDoc.objects.filter(branch=branch)
        if year:
            qs = qs.filter(year=year)
        if semester:
            qs = qs.filter(semester=semester)
        scheme_pdfs = qs.order_by('-created_at')
    except LookupError:
        scheme_pdfs = []

    # faculty PDFs (hod.FacultySyllabusPDF) — show approved or not; selection template filters approved
    faculty_pdfs = []
    try:
        FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
        qs = FacultySyllabusPDF.objects.filter(branch=branch)
        if year:
            if 'year' in [f.name for f in FacultySyllabusPDF._meta.get_fields()]:
                qs = qs.filter(year=year)
            elif 'academic_year' in [f.name for f in FacultySyllabusPDF._meta.get_fields()]:
                qs = qs.filter(academic_year=year)
        if semester:
            if 'semester' in [f.name for f in FacultySyllabusPDF._meta.get_fields()]:
                qs = qs.filter(semester=semester)
        faculty_pdfs = qs.order_by('-created_at')
    except LookupError:
        faculty_pdfs = []

    context = {
        'branch': branch,
        'scheme_pdfs': scheme_pdfs,
        'faculty_pdfs': faculty_pdfs,
        'selected_year': year,
        'selected_semester': semester,
    }
    return render(request, 'hod/create_combined_syllabus.html', context)
