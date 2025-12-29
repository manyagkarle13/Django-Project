import os
import logging
from io import BytesIO
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Prefetch
from django.db import transaction
from django.core.exceptions import FieldError
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
import os

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
            # Fetch dean courses: include college-wide (branch is null) or those assigned to this branch
            dean_qs = CollegeLevelCourse.objects.filter(department="All Branches", is_deleted=False).filter(
                Q(branch__isnull=True) | Q(branch=branch)
            )
            # filter by semester only if model has that field
            if hasattr(CollegeLevelCourse, 'semester'):
                try:
                    dean_qs = dean_qs.filter(semester=int(semester))
                except Exception:
                    dean_qs = dean_qs.filter(semester=semester)
            # filter by admission_year if model supports it (STRICT: only include courses with matching year when provided)
            for year_field in ['admission_year', 'year', 'academic_year']:
                if hasattr(CollegeLevelCourse, year_field) and year not in (None, '', 0):
                    try:
                        dean_qs = dean_qs.filter(**{year_field: int(year)})
                    except Exception:
                        try:
                            dean_qs = dean_qs.filter(**{year_field: str(year)})
                        except Exception:
                            pass
                    break
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
        # Fetch dean courses: include college-wide (branch is null) or those assigned to this branch
        dean_qs = CollegeLevelCourse.objects.filter(department="All Branches", is_deleted=False).filter(
            Q(branch__isnull=True) | Q(branch=branch)
        )
        # filter by semester only if model has that field
        if hasattr(CollegeLevelCourse, 'semester'):
            try:
                dean_qs = dean_qs.filter(semester=semester)
            except Exception:
                pass
        # filter by admission_year if model supports it (STRICT: only include courses with matching year when provided)
        for year_field in ['admission_year', 'year', 'academic_year']:
            if hasattr(CollegeLevelCourse, year_field) and year not in (None, '', 0):
                try:
                    dean_qs = dean_qs.filter(**{year_field: int(year)})
                except Exception:
                    try:
                        dean_qs = dean_qs.filter(**{year_field: str(year)})
                    except Exception:
                        pass
                break

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
        ).select_related('faculty')
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
        ).select_related('faculty')
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

@login_required
def dashboard(request, branch_pk=None):
    """Main HOD dashboard for a branch."""
    if not Branch or not Course:
        # academics app models not available
        return render(request, 'hod/hod_dashboard.html', {
            'branch': None, 'courses_dean': [], 'total_credits': 0, 'selected_year': '', 'selected_semester': ''
        })

    if branch_pk is None:
        # no branch supplied — redirect to the HOD's assigned branch if possible
        return dashboard_redirect(request)
    else:
        branch = get_object_or_404(Branch, pk=branch_pk)

    # selected year and semester from querystring (dashboard shows semester credits/courses when both present)
    selected_year = request.GET.get('year', '').strip()
    selected_semester = request.GET.get('semester', '').strip()

    # ensure this variable always exists to avoid UnboundLocalError
    selected_sem_credit = None

    # get CollegeLevelCourse model
    CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')

    courses_dean = []
    total_credits = 0

    # Only fetch semester credits and dean courses when admission year is provided.
    semester_rows = []
    semester_credit_obj = None
    if selected_year:
        # try to get SemesterCredit record and build a safe list of semester rows for template
        semester_rows = []
        semester_credit_obj = None
        if selected_year:
            try:
                SemesterCredit = apps.get_model('academics', 'SemesterCredit')

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
            except LookupError:
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
    if selected_year and selected_semester:
        try:
            CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        except LookupError:
            logger.warning("academics.CollegeLevelCourse model not found")
            courses_dean = []
        else:
            # safe dean course queryset for branch or college-wide
            # Filter by year and semester if model supports these fields
            try:
                # Fetch dean courses for this branch/year/semester (college-wide or branch-specific)
                dean_qs = CollegeLevelCourse.objects.filter(department="All Branches", is_deleted=False).filter(
                    Q(branch__isnull=True) | Q(branch=branch)
                )
                # if model has semester field, filter by sem
                if hasattr(CollegeLevelCourse, 'semester'):
                    try:
                        dean_qs = dean_qs.filter(semester=int(selected_semester))
                    except Exception:
                        try:
                            dean_qs = dean_qs.filter(semester=selected_semester)
                        except Exception:
                            pass
                # if model has admission_year or year field, filter by year (STRICT match - only include courses for the given admission year)
                if selected_year:
                    for year_field in ['admission_year', 'year', 'academic_year']:
                        if hasattr(CollegeLevelCourse, year_field):
                            try:
                                dean_qs = dean_qs.filter(**{year_field: int(selected_year)})
                                break
                            except Exception:
                                try:
                                    dean_qs = dean_qs.filter(**{year_field: selected_year})
                                    break
                                except Exception:
                                    pass
            except Exception:
                dean_qs = CollegeLevelCourse.objects.none()

            # Convert to simple dicts (make faculty_id an int or None)
            courses_dean = []
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
        # keep empty when not selected
        courses_dean = []

    # Pending/Approved syllabi display removed — feature disabled
    pending_submissions = []
    approved_submissions = []
    
    # Also fetch SyllabusSubmission if it exists (for backward compatibility)
    if SyllabusSubmission:
        try:
            syllabus_submissions = SyllabusSubmission.objects.filter(course__branch=branch, status='PENDING')
            # Combine both types if needed (for now, prioritize FacultySyllabusPDF)
        except Exception:
            pass

    # robustly compute total credits (works for model instances *or* dicts)
    total_credits_dean = 0
    if courses_dean:
        for c in courses_dean:
            try:
                # model instance path
                val = getattr(c, 'credits', None)
                if val is None and isinstance(c, dict):
                    # dict fallback
                    val = c.get('credits', 0)
                total_credits_dean += int(val or 0)
            except Exception:
                # last resort: try dict get or treat as 0
                try:
                    total_credits_dean += int(c.get('credits', 0))
                except Exception:
                    pass

    # If you have your own schema model, fetch credits for the selected sem
    total_credits_schema = 0
    if selected_year and selected_semester:
        try:
            SemesterCredit = apps.get_model('academics', 'SemesterCredit')
            obj = SemesterCredit.objects.filter(
                branch=branch,
                admission_year=selected_year
            ).first()
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
        'selected_year': selected_year,
        'selected_semester': selected_semester,
        'semester_rows': semester_rows,
        'selected_sem_credit': selected_sem_credit,
        'total_credits_dean': total_credits_dean,
        'total_credits_schema': total_credits_schema,
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
    """Redirect to combined syllabus creation page."""
    branch = get_object_or_404(Branch, pk=branch_pk)
    year = request.POST.get('academic_year', '') or request.POST.get('year', '')
    semester = request.POST.get('semester', '')
    
    # Redirect to combined syllabus creation page
    return redirect(reverse('hod:create_combined_syllabus', args=[branch_pk]) + f"?year={year}&semester={semester}")

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
    """View/download a faculty syllabus PDF submission (legacy name)."""
    return view_submission_pdf(request, submission_pk)

@login_required
def view_submission_pdf(request, submission_pk):
    """View/download a faculty syllabus PDF submission."""
    try:
        FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
        pdf_obj = get_object_or_404(FacultySyllabusPDF, pk=submission_pk)
        
        # Verify HOD has access to this branch's submissions
        hod_assignment = getattr(request.user, 'hod_assignment', None)
        if hod_assignment and pdf_obj.branch and pdf_obj.branch != hod_assignment.branch:
            messages.error(request, "You don't have permission to view this submission.")
            return redirect('hod:dashboard_redirect')
        
        # Serve the PDF file (return HttpResponse with content so tests can inspect `response.content`)
        if pdf_obj.pdf_file:
            import os
            if os.path.exists(pdf_obj.pdf_file.path):
                try:
                    with open(pdf_obj.pdf_file.path, 'rb') as f:
                        data = f.read()
                    response = HttpResponse(data, content_type='application/pdf')
                    response['Content-Disposition'] = f'inline; filename="{os.path.basename(pdf_obj.pdf_file.name)}"'
                    return response
                except Exception as e:
                    logger.exception("Failed reading PDF file for response: %s", e)
                    messages.error(request, "Failed to read PDF file.")
                    return redirect('hod:dashboard_redirect')
            else:
                messages.error(request, "PDF file not found.")
                return redirect('hod:dashboard_redirect')
        else:
            messages.error(request, "No PDF file available for this submission.")
            return redirect('hod:dashboard_redirect')
    except LookupError:
        messages.error(request, "FacultySyllabusPDF model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error viewing submission PDF: %s", e)
        messages.error(request, f"Failed to view PDF: {e}")
        return redirect('hod:dashboard_redirect')

@require_http_methods(["POST"])
@login_required
def approve_syllabus(request, submission_pk):
    """Approve or reject a FacultySyllabusPDF submission."""
    try:
        FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
        pdf_obj = get_object_or_404(FacultySyllabusPDF, pk=submission_pk)
        
        action = request.POST.get('action', 'approve')  # 'approve' or 'reject'
        
        if action == 'approve':
            pdf_obj.approved = True
            pdf_obj.rejected = False  # Clear rejection if re-approved
            pdf_obj.approved_by = request.user
            pdf_obj.approved_at = timezone.now()
            pdf_obj.rejected_at = None
            pdf_obj.rejected_by = None
            pdf_obj.save()
            messages.success(request, f"Syllabus approved successfully.")
        elif action == 'reject':
            # Mark as rejected and remove from pending
            pdf_obj.approved = False
            pdf_obj.rejected = True
            pdf_obj.rejected_by = request.user
            pdf_obj.rejected_at = timezone.now()
            pdf_obj.save()
            messages.success(request, f"Syllabus rejected.")
        
        # Redirect back to dashboard with year/semester if provided
        branch_pk = pdf_obj.branch.pk if pdf_obj.branch else None
        if branch_pk:
            redirect_url = reverse('hod:dashboard_self', args=[branch_pk])
            if pdf_obj.year:
                redirect_url += f"?year={pdf_obj.year}"
            if pdf_obj.semester:
                redirect_url += f"&semester={pdf_obj.semester}"
            return redirect(redirect_url)
        return redirect('hod:dashboard_redirect')
    except LookupError:
        messages.error(request, "FacultySyllabusPDF model not found.")
        return redirect('hod:dashboard_redirect')
    except Exception as e:
        logger.exception("Error approving syllabus: %s", e)
        messages.error(request, f"Failed to approve syllabus: {e}")
        return redirect('hod:dashboard_redirect')

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
            from . import pdf_generator
            pdf_path = pdf_generator.generate_start_pages_pdf(branch, y)
            messages.success(request, f'Starting pages generated: {pdf_path}')
        except ImportError as ie:
            messages.error(request, f"PDF generation dependency missing: {ie}. Install with: pip install reportlab")
        except Exception as e:
            logger.exception("Error generating starting pages PDF")
            messages.warning(request, f"Could not generate starting pages: {e}")
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
    # Try to render edit_semester_schema.html, fallback to create_scheme.html with edit_mode
    try:
        return render(request, 'hod/edit_semester_schema.html', context)
    except Exception as e:
        # If template doesn't exist, fallback to create_scheme.html with edit_mode flag
        logger.warning("edit_semester_schema.html not found, using create_scheme.html fallback: %s", e)
        context['edit_mode'] = True
        return render(request, 'hod/create_scheme.html', context)

@login_required
def create_scheme_form(request, branch_pk, year, semester):
    """GET-only form for creating a scheme (no POST handling here)."""
    branch = get_object_or_404(Branch, pk=branch_pk)
    
    # safe dean course queryset for branch or college-wide
    try:
        # Fetch dean courses for this branch/year/semester (college-wide or branch-specific)
        dean_qs = Course.objects.filter(department="All Branches", is_deleted=False).filter(
            Q(branch__isnull=True) | Q(branch=branch)
        )
        # if model has semester field, filter by sem
        if hasattr(Course, 'semester'):
            try:
                dean_qs = dean_qs.filter(semester=semester)
            except Exception:
                # if semester field uses string/other format, try cast
                pass
        # if model has admission_year (or similar), filter by provided year (STRICT match when provided)
        for year_field in ['admission_year', 'year', 'academic_year']:
            if hasattr(Course, year_field) and year not in (None, '', 0):
                try:
                    dean_qs = dean_qs.filter(**{year_field: year})
                except Exception:
                    try:
                        dean_qs = dean_qs.filter(**{year_field: str(year)})
                    except Exception:
                        pass
                break
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
        # Fetch dean courses for this branch/year/semester (college-wide or branch-specific)
        dean_qs = CollegeLevelCourse.objects.filter(department="All Branches", is_deleted=False).filter(
            Q(branch__isnull=True) | Q(branch=branch)
        )
        # filter by semester only if model has that field
        if hasattr(CollegeLevelCourse, 'semester'):
            try:
                dean_qs = dean_qs.filter(semester=int(semester))
            except Exception:
                dean_qs = dean_qs.filter(semester=semester)
        # filter by admission_year if model supports it (STRICT when 'year' provided)
        for year_field in ['admission_year', 'year', 'academic_year']:
            if hasattr(CollegeLevelCourse, year_field) and year not in (None, '', 0):
                try:
                    dean_qs = dean_qs.filter(**{year_field: int(year)})
                except Exception:
                    try:
                        dean_qs = dean_qs.filter(**{year_field: year})
                    except Exception:
                        pass
                break

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

    # Collect posted main_rows with faculty names AND save them to DB before PDF generation
    # This ensures all rows are persisted and included in PDF
    posted_main_rows = []
    posted_elective_rows = []
    found_post = False
    hod_assignment = getattr(request.user, 'hod_assignment', None)
    
    i = 1
    while True:
        code = request.POST.get(f'code_new_{i}', '').strip()
        title = request.POST.get(f'title_new_{i}', '').strip()
        if not code and not title:
            break
        found_post = True
        
        faculty_name = ''
        faculty_id = request.POST.get(f'faculty_new_{i}')
        faculty_user = None
        if faculty_id:
            try:
                faculty_user = CustomUser.objects.get(pk=int(faculty_id))
                faculty_name = faculty_user.get_full_name() or faculty_user.username
            except Exception:
                faculty_name = ''
        
        # Save main row to DB before PDF generation
        try:
            SchemeCourse = apps.get_model('hod', 'SchemeCourse')
            with transaction.atomic():
                l = int(request.POST.get(f'l_new_{i}', 0) or 0)
                t = int(request.POST.get(f't_new_{i}', 0) or 0)
                p = int(request.POST.get(f'p_new_{i}', 0) or 0)
                total_hours = l + t + p
                cie = int(request.POST.get(f'cie_new_{i}', 0) or 0)
                see = int(request.POST.get(f'see_new_{i}', 0) or 0)
                total_marks = cie + see
                credits = float(request.POST.get(f'credits_new_{i}', 0) or 0)
                category = request.POST.get(f'category_new_{i}', '') or ''
                
                sc, _ = SchemeCourse.objects.update_or_create(
                    branch=branch,
                    year=int(year),
                    semester=int(semester),
                    course_code=code,
                    defaults={
                        'course_title': title or '',
                        'l': l,
                        't': t,
                        'p': p,
                        'total_hours': total_hours,
                        'cie': cie,
                        'see': see,
                        'total_marks': total_marks,
                        'credits': Decimal(str(credits)) if credits else Decimal('0.0'),
                        'category': category,
                        'is_elective': False,
                        'faculty': faculty_user,
                    }
                )
        except Exception as e:
            logger.exception("Error saving main row %s in generate_pdf_view: %s", code, e)
        
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

    # Collect posted elective rows with faculty names AND save them to DB before PDF generation
    # This ensures electives are persisted and included in PDF
    # Handle both regular and additional elective rows
    for section in ['pec', 'oec', 'esc', 'aec']:
        # Process regular elective rows
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
            
            # Save elective to DB before PDF generation to ensure it's included
            try:
                SchemeCourse = apps.get_model('hod', 'SchemeCourse')
                with transaction.atomic():
                    faculty_user = None
                    if faculty_id:
                        try:
                            faculty_user = CustomUser.objects.get(pk=int(faculty_id))
                        except Exception:
                            pass
                    
                    sc, created = SchemeCourse.objects.update_or_create(
                        branch=branch,
                        year=int(year),
                        semester=int(semester),
                        course_code=code,
                        defaults={
                            'course_title': title or '',
                            'category': section.upper(),
                            'is_elective': True,
                            'faculty': faculty_user,
                        }
                    )
                    
                    # Create/update CourseAllocation and FacultyAssignment
                    if hod_assignment:
                        CourseAllocation = apps.get_model('hod', 'CourseAllocation')
                        FacultyAssignment = apps.get_model('hod', 'FacultyAssignment')
                        course_alloc, _ = CourseAllocation.objects.get_or_create(
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
                                faculty_profile, _ = Faculty.objects.get_or_create(
                                    user=u,
                                    defaults={'department': getattr(hod_assignment.branch, 'name', '') if hod_assignment else ''}
                                )
                                FacultyAssignment.objects.update_or_create(
                                    course_allocation=course_alloc,
                                    defaults={'faculty': faculty_profile, 'assigned_on': timezone.now()}
                                )
                            except Exception:
                                pass
            except Exception as e:
                logger.exception("Error saving elective %s: %s", code, e)
            
            posted_elective_rows.append({
                'section': section.upper(),
                'code': code,
                'title': title,
                'faculty_name': faculty_name,
            })
            j += 1
        
        # Process additional elective rows (additional_pec_code_1, etc.)
        j_add = 1
        while True:
            code = request.POST.get(f'additional_{section}_code_{j_add}', '').strip()
            title = request.POST.get(f'additional_{section}_title_{j_add}', '').strip()
            if not code and not title:
                break
            found_post = True
            
            faculty_name = ''
            faculty_id = request.POST.get(f'additional_{section}_faculty_{j_add}')
            if faculty_id:
                try:
                    u = CustomUser.objects.get(pk=int(faculty_id))
                    faculty_name = u.get_full_name() or u.username
                except Exception:
                    faculty_name = ''
            
            # Save additional elective to DB before PDF generation
            try:
                SchemeCourse = apps.get_model('hod', 'SchemeCourse')
                with transaction.atomic():
                    faculty_user = None
                    if faculty_id:
                        try:
                            faculty_user = CustomUser.objects.get(pk=int(faculty_id))
                        except Exception:
                            pass
                    
                    sc, created = SchemeCourse.objects.update_or_create(
                        branch=branch,
                        year=int(year),
                        semester=int(semester),
                        course_code=code,
                        defaults={
                            'course_title': title or '',
                            'category': section.upper(),
                            'is_elective': True,
                            'faculty': faculty_user,
                        }
                    )
                    
                    # Create/update CourseAllocation and FacultyAssignment
                    if hod_assignment:
                        CourseAllocation = apps.get_model('hod', 'CourseAllocation')
                        FacultyAssignment = apps.get_model('hod', 'FacultyAssignment')
                        course_alloc, _ = CourseAllocation.objects.get_or_create(
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
                                faculty_profile, _ = Faculty.objects.get_or_create(
                                    user=u,
                                    defaults={'department': getattr(hod_assignment.branch, 'name', '') if hod_assignment else ''}
                                )
                                FacultyAssignment.objects.update_or_create(
                                    course_allocation=course_alloc,
                                    defaults={'faculty': faculty_profile, 'assigned_on': timezone.now()}
                                )
                            except Exception:
                                pass
            except Exception as e:
                logger.exception("Error saving additional elective %s: %s", code, e)
            
            posted_elective_rows.append({
                'section': section.upper(),
                'code': code,
                'title': title,
                'faculty_name': faculty_name,
            })
            j_add += 1

    # After saving POST data, always fetch from DB to ensure all saved rows are included
    # This ensures that even if POST data is incomplete, all persisted rows appear in PDF
    # _fetch_db_rows_for_scheme already includes dean courses, so use it as the source of truth
    hod_scheme_rows = _fetch_db_rows_for_scheme(branch, int(year), int(semester))
    if isinstance(hod_scheme_rows, tuple):
        hod_main, hod_elec = hod_scheme_rows
        # Use DB-fetched rows as base (includes dean courses + HOD scheme courses)
        main_rows = hod_main[:]
        
        # If POST had main rows that aren't in DB yet (edge case), merge them
        if found_post and posted_main_rows:
            db_codes = {r.get('code') for r in main_rows}
            for posted_row in posted_main_rows:
                if posted_row.get('code') not in db_codes:
                    main_rows.append(posted_row)
        
        # Use DB-fetched elective rows as base
        elective_rows = hod_elec[:]
        
        # If POST had elective rows that aren't in DB yet, merge them (avoid duplicates by code)
        if found_post and posted_elective_rows:
            db_elec_codes = {e.get('code') for e in elective_rows}
            for posted_elec in posted_elective_rows:
                if posted_elec.get('code') not in db_elec_codes:
                    elective_rows.append(posted_elec)
    else:
        # Fallback: use dean_rows + posted data if DB fetch fails
        main_rows = dean_rows[:]
        if found_post:
            main_rows.extend(posted_main_rows)
        elective_rows = posted_elective_rows[:]

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


# Note: Model imports are already at the top of the file

@login_required
def faculty_assignments_detail(request, branch_pk):
    """
    Show assigned faculty for a branch, filtered by ?year=&semester=.
    This view is defensive: SchemeCourse may not have a direct 'branch' field.
    We attempt to filter via Scheme (scheme__branch / scheme__branch_id / scheme__branch__pk)
    and attempt several possible year/semester field names. If year/semester were requested
    but we cannot find scheme rows for them, we return an empty list (so user sees nothing
    for that selection rather than wrong assignments).
    """
    # Use models imported at top of file
    try:
        SchemeCourse = apps.get_model('hod', 'SchemeCourse')
        HODAssignment = apps.get_model('hod', 'HODAssignment')
    except LookupError:
        messages.error(request, "Required models not found.")
        return redirect('hod:dashboard_redirect')
    
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
        HODAssignment = apps.get_model('hod', 'HODAssignment')
        hod_assignment = HODAssignment.objects.get(branch=branch)
    except (LookupError, Exception):
        hod_assignment = None

    # Build scheme_qs - filter by branch, year, and semester (all required for accurate filtering)
    # If year or semester is missing, show message to user instead of showing all/None
    if year is None or semester is None:
        messages.info(request, "Please select both year and semester from the dashboard to view assignments.")
        return redirect('hod:dashboard_self', branch_pk=branch_pk)
    
    try:
        SchemeCourse = apps.get_model('hod', 'SchemeCourse')
    except LookupError:
        messages.error(request, "SchemeCourse model not found.")
        return redirect('hod:dashboard_redirect')
    
    # Filter SchemeCourse by branch, year, and semester (direct fields now available)
    scheme_qs = SchemeCourse.objects.filter(
        branch=branch,
        year=year,
        semester=semester
    ).select_related('faculty', 'branch').order_by('course_code')

    # Collect course codes from scheme rows (these identify the courses for that branch/year/sem)
    # Also get the actual SchemeCourse objects for faculty assignment display (per-scheme assignments)
    scheme_codes = list(scheme_qs.values_list('course_code', flat=True).distinct())
    scheme_courses_list = list(scheme_qs.select_related('faculty'))

    # Get CourseAllocation and FacultyAssignment models (for backward compatibility)
    try:
        CourseAllocation = apps.get_model('hod', 'CourseAllocation')
        FacultyAssignment = apps.get_model('hod', 'FacultyAssignment')
    except LookupError:
        messages.error(request, "Required models not found.")
        return redirect('hod:dashboard_redirect')
    
    # Build assignments list - prioritize SchemeCourse (per-scheme assignments) over CourseAllocation
    assignments = []
    
    # First, add assignments directly from SchemeCourse (these are per-scheme, most accurate)
    for sc in scheme_courses_list:
        faculty_name = None
        if sc.faculty:
            faculty_name = sc.faculty.get_full_name() or sc.faculty.username
        
        # Get course title from SchemeCourse or try CourseAllocation as fallback
        course_title = getattr(sc, 'course_title', '') or ''
        if not course_title and hod_assignment:
            try:
                ca = CourseAllocation.objects.filter(
                    hod_assignment=hod_assignment,
                    course_code=sc.course_code
                ).first()
                if ca:
                    course_title = getattr(ca, 'course_title', '') or ''
            except Exception:
                pass
        
        assignments.append({
            'course_code': sc.course_code,
            'course_title': course_title,
            'year': sc.year,  # Now available directly on SchemeCourse
            'semester': sc.semester,
            'assigned_faculty_name': faculty_name or 'Not assigned',
            'assigned_on': sc.updated_at if sc.faculty else None,
            'course_allocation_id': None,  # From SchemeCourse, not CourseAllocation
            'from_scheme_course': True,  # Flag to indicate this is from SchemeCourse
        })
    
    # Then add assignments from CourseAllocation for courses not already in SchemeCourse (backward compatibility)
    # Only if year/semester not specified (show all) or if we have scheme codes
    if (year is None and semester is None) or scheme_codes:
        if hod_assignment:
            if scheme_codes:
                course_alloc_qs = CourseAllocation.objects.filter(
                    hod_assignment=hod_assignment, 
                    course_code__in=scheme_codes
                )
            else:
                # no year/sem selected -> show allocations for the HOD
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

        for ca in course_alloc_qs:
            # Skip if already added from SchemeCourse
            if any(a.get('course_code') == ca.course_code and a.get('from_scheme_course') for a in assignments):
                continue
                
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
                'year': year,  # From query params
                'semester': semester,  # From query params
                'credits': getattr(ca, 'credits', None),
                'assigned_faculty_name': assigned_faculty_name,
                'assigned_on': assigned_on,
                'course_allocation_id': ca.id,
                'from_scheme_course': False,  # From CourseAllocation
            })

    # Remove duplicates by course_code (prefer SchemeCourse entries) and sort
    seen_codes = set()
    unique_assignments = []
    for a in assignments:
        if a['course_code'] not in seen_codes:
            seen_codes.add(a['course_code'])
            unique_assignments.append(a)
    assignments = sorted(unique_assignments, key=lambda x: x['course_code'])

    context = {
        'branch': branch,
        'year': year,
        'semester': semester,
        'assignments': assignments,
        'hod_assignment': hod_assignment,
    }
    return render(request, 'hod/faculty_assignments_detail.html', context)

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
def create_combined_syllabus(request, branch_pk):
    """Display form to create combined syllabus with checkboxes for scheme and approved PDFs."""
    branch = get_object_or_404(Branch, pk=branch_pk)
    year = request.GET.get('year', '').strip()
    semester = request.GET.get('semester', '').strip()
    
    # Get available schemes for this branch/year/semester and pick the latest one to include automatically
    schemes = []
    latest_scheme = None
    try:
        SchemeDocument = apps.get_model('hod', 'SchemeDocument')
        scheme_qs = SchemeDocument.objects.filter(branch=branch, is_deleted=False)
        if year:
            try:
                scheme_qs = scheme_qs.filter(year=int(year))
            except ValueError:
                pass
        if semester:
            try:
                scheme_qs = scheme_qs.filter(semester=int(semester))
            except ValueError:
                pass
        schemes = scheme_qs.order_by('-created_at')
        latest_scheme = schemes.first() if schemes else None
    except LookupError:
        pass
    
    # Build latest faculty-generated PDF per course (one latest per course)
    latest_faculty_list = []
    dean_courses_with_pdf = []
    # Only expose faculty-generated PDFs to users who are actual HODs (hide from Dean/staff views)
    if getattr(request.user, 'hod_assignment', None):
        try:
            FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
            pdf_qs = FacultySyllabusPDF.objects.filter(branch=branch)
            if year:
                pdf_qs = pdf_qs.filter(year=str(year))
            if semester:
                pdf_qs = pdf_qs.filter(semester=str(semester))
            try:
                latest_qs = pdf_qs.select_related('course', 'created_by').order_by('course_id', '-created_at')
                latest_map = {}
                for p in latest_qs:
                    cid = getattr(p, 'course_id', None)
                    if cid and cid not in latest_map:
                        latest_map[cid] = p
                latest_faculty_list = [latest_map[cid] for cid in sorted(latest_map.keys())]
            except Exception:
                latest_faculty_list = []
        except LookupError:
            latest_faculty_list = []

    # Get dean college-level courses that may have a `syllabus_pdf` file to include
    try:
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        dean_courses_qs = CollegeLevelCourse.objects.filter(department="All Branches", is_deleted=False).filter(
            Q(branch__isnull=True) | Q(branch=branch)
        )
        if semester and hasattr(CollegeLevelCourse, 'semester'):
            try:
                dean_courses_qs = dean_courses_qs.filter(semester=semester)
            except Exception:
                pass
        # strict year/admission_year filter if available
        for year_field in ['admission_year', 'year', 'academic_year']:
            if hasattr(CollegeLevelCourse, year_field) and year not in (None, '', 0):
                try:
                    dean_courses_qs = dean_courses_qs.filter(**{year_field: int(year)})
                except Exception:
                    try:
                        dean_courses_qs = dean_courses_qs.filter(**{year_field: str(year)})
                    except Exception:
                        pass
                break
        # Include all dean courses (branch-wide or branch-specific); mark files as present or not in template
        dean_courses = []
        for course in dean_courses_qs.order_by('course_code'):
            dean_courses.append(course)
    except LookupError:
        pass

    context = {
        'branch': branch,
        'branch_pk': branch_pk,
        'year': year,
        'semester': semester,
        'schemes': schemes,
        'latest_scheme': latest_scheme,
        'latest_faculty_list': latest_faculty_list,
        'dean_courses': dean_courses,
    }
    return render(request, 'hod/create_combined_syllabus.html', context)


@require_http_methods(["POST"])
@login_required
def generate_combined_syllabus(request, branch_pk):
    """Generate combined syllabus PDF by merging scheme and approved faculty PDFs."""
    try:
        branch = get_object_or_404(Branch, pk=branch_pk)
        year = request.POST.get('year', '').strip()
        semester = request.POST.get('semester', '').strip()
        
        # HOD scheme and dean course PDFs are included automatically (no form selection required)
        include_hod = True
        scheme_id = None
        
        # We no longer support selecting arbitrary approved faculty PDFs for merging.
        # Selections are limited to 'Dean course PDFs' and 'Latest faculty-generated PDF per course'.
        # Import PyPDF2 for PDF merging
        try:
            from PyPDF2 import PdfMerger
        except ImportError:
            messages.error(request, "PyPDF2 library required for PDF merging. Install with: pip install PyPDF2")
            return redirect('hod:create_combined_syllabus', branch_pk=branch_pk)
        
        # Merge PDFs using PyPDF2.PdfMerger (preserves POST order)
        try:
            merger = PdfMerger()

            # Keep track of file paths already appended to avoid duplicates
            appended_paths = set()

            # Add latest HOD scheme PDF first (mandatory if present)
            try:
                SchemeDocument = apps.get_model('hod', 'SchemeDocument')
                scheme_qs = SchemeDocument.objects.filter(branch=branch, is_deleted=False).order_by('-created_at')
                if year:
                    try:
                        scheme_qs = scheme_qs.filter(year=int(year))
                    except Exception:
                        pass
                if semester:
                    try:
                        scheme_qs = scheme_qs.filter(semester=int(semester))
                    except Exception:
                        pass
                scheme = scheme_qs.first()
                if scheme and getattr(scheme, 'pdf_file', None) and os.path.exists(scheme.pdf_file.path):
                    path = scheme.pdf_file.path
                    if path not in appended_paths:
                        merger.append(path)
                        appended_paths.add(path)
            except LookupError:
                scheme = None
            except Exception as e:
                logger.exception("Error adding latest scheme PDF: %s", e)
                messages.warning(request, f"Could not add scheme PDF: {e}")

            # Add dean course PDFs (mandatory for inclusion if they have files and match filters)
            try:
                CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
            except LookupError:
                CollegeLevelCourse = None
            if CollegeLevelCourse:
                dean_courses_qs = CollegeLevelCourse.objects.filter(
                    department="All Branches",
                    is_deleted=False,
                    branch__isnull=True,
                ).order_by('course_code')
                if semester and hasattr(CollegeLevelCourse, 'semester'):
                    try:
                        dean_courses_qs = dean_courses_qs.filter(semester=semester)
                    except Exception:
                        pass
                for year_field in ['admission_year', 'year', 'academic_year']:
                    if hasattr(CollegeLevelCourse, year_field) and year not in (None, '', 0):
                        try:
                            dean_courses_qs = dean_courses_qs.filter(**{year_field: int(year)})
                        except Exception:
                            try:
                                dean_courses_qs = dean_courses_qs.filter(**{year_field: str(year)})
                            except Exception:
                                pass
                        break

                for course in dean_courses_qs:
                    try:
                        pdf_field = getattr(course, 'syllabus_pdf', None)
                        # If a dean course has an attached PDF file that exists on disk, append it
                        if pdf_field and hasattr(pdf_field, 'path') and os.path.exists(pdf_field.path):
                            path = pdf_field.path
                            if path in appended_paths:
                                continue
                            try:
                                merger.append(path)
                                appended_paths.add(path)
                            except Exception as e:
                                logger.exception("Error adding dean course PDF (id=%s): %s", course.pk, e)
                                messages.warning(request, f"Could not add dean course PDF for {course.course_code}: {e}")
                                # fallback placeholder for unreadable file
                                try:
                                    from io import BytesIO
                                    from reportlab.pdfgen import canvas
                                    tmp = BytesIO()
                                    c = canvas.Canvas(tmp)
                                    c.drawString(50, 800, f"Placeholder: unreadable dean course file (id={course.pk})")
                                    c.showPage()
                                    c.save()
                                    tmp.seek(0)
                                    merger.append(tmp)
                                    appended_paths.add(f"dean_placeholder_{course.pk}")
                                    logger.warning("Appended placeholder PDF for unreadable dean course file id: %s", course.pk)
                                except Exception:
                                    logger.exception("Failed to append placeholder PDF for dean course id %s", course.pk)
                        else:
                            # No PDF file attached for this dean course — append a small placeholder indicating the course
                            try:
                                from io import BytesIO
                                from reportlab.pdfgen import canvas
                                tmp = BytesIO()
                                c = canvas.Canvas(tmp)
                                c.drawString(50, 800, f"Placeholder: no dean course PDF for {getattr(course, 'course_code', 'unknown')} - {getattr(course, 'course_title', '')}")
                                c.showPage()
                                c.save()
                                tmp.seek(0)
                                merger.append(tmp)
                                appended_paths.add(f"dean_placeholder_{course.pk}")
                                logger.info("Appended placeholder for dean course with no file: %s", course.pk)
                            except Exception:
                                logger.exception("Failed to append placeholder for dean course id %s", course.pk)
                    except Exception:
                        continue

            # Ensure FacultySyllabusPDF model is available for latest selections
            try:
                FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
            except LookupError:
                FacultySyllabusPDF = None

            # Add selected latest faculty PDFs (one per course) — allowed only for HOD users
            latest_ids = request.POST.getlist('latest_submissions')
            if latest_ids and FacultySyllabusPDF:
                if not getattr(request.user, 'hod_assignment', None):
                    messages.warning(request, "Only HOD users can include faculty-generated PDFs in the combined syllabus.")
                else:
                    for lid in latest_ids:
                        try:
                            sub = FacultySyllabusPDF.objects.get(pk=lid)
                            if sub.pdf_file and os.path.exists(sub.pdf_file.path):
                                path = sub.pdf_file.path
                                if path not in appended_paths:
                                    try:
                                        merger.append(path)
                                        appended_paths.add(path)
                                    except Exception as e:
                                        logger.exception("Error adding latest faculty PDF (id=%s): %s", lid, e)
                                        messages.warning(request, f"Could not add one latest faculty PDF: {e}")
                                        try:
                                            from io import BytesIO
                                            from reportlab.pdfgen import canvas
                                            tmp = BytesIO()
                                            c = canvas.Canvas(tmp)
                                            c.drawString(50, 800, f"Placeholder: unreadable faculty PDF (id={lid})")
                                            c.showPage()
                                            c.save()
                                            tmp.seek(0)
                                            merger.append(tmp)
                                            appended_paths.add(path)
                                            logger.warning("Appended placeholder PDF for unreadable faculty file: %s", path)
                                        except Exception:
                                            logger.exception("Failed to append placeholder PDF for faculty PDF id %s", lid)
                        except Exception as e:
                            logger.exception("Error adding latest faculty PDF (id=%s): %s", lid, e)
                            messages.warning(request, f"Could not add one latest faculty PDF: {e}")
            
            # Create output buffer
            # Ensure we actually appended something
            if not appended_paths:
                messages.error(request, "No PDFs were available to merge for the selected filters/selections.")
                return redirect('hod:create_combined_syllabus', branch_pk=branch_pk)

            # Create output buffer
            output_buffer = BytesIO()
            merger.write(output_buffer)
            merger.close()
            output_buffer.seek(0)

            # Return merged PDF as FileResponse
            response = FileResponse(
                output_buffer,
                content_type='application/pdf',
                filename='Combined_Syllabus.pdf'
            )
            response['Content-Disposition'] = 'attachment; filename="Combined_Syllabus.pdf"'
            return response
            
        except Exception as e:
            logger.exception("Error merging PDFs: %s", e)
            messages.error(request, f"Failed to merge PDFs: {e}")
            return redirect('hod:create_combined_syllabus', branch_pk=branch_pk)
            
    except Exception as e:
        logger.exception("Error generating combined syllabus: %s", e)
        messages.error(request, "An unexpected error occurred while generating the combined PDF.")
        return redirect('hod:create_combined_syllabus', branch_pk=branch_pk)
    # fallback - should never reach here
    return redirect('hod:create_combined_syllabus', branch_pk=branch_pk)


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


@login_required
def create_scheme(request, branch_pk, year, semester):
    """
    HOD: show scheme form (GET) and save submitted scheme rows (POST).
    When HOD saves rows this ensures CourseAllocation and FacultyAssignment objects
    are created/updated for the HOD (linked via HODAssignment).
    """
    branch = get_object_or_404(Branch, pk=branch_pk)
    faculty_list = CustomUser.objects.filter(role='faculty', is_active=True)

    # Build Dean course list (display only) - Include courses assigned by Dean for admission_year & sem in create scheme and in PDF
    # Use CollegeLevelCourse (imported as Course) which represents dean-assigned courses
    dean_courses = []
    if Course is not None:
        try:
            # Filter by branch (college-wide courses have branch=None, branch-specific have branch=branch)
            dean_qs = Course.objects.filter(
                department="All Branches",  # Only college-level courses
                is_deleted=False,  # Exclude deleted courses
                branch__isnull=True,
            )
            # Filter by semester if model has semester field
            if hasattr(Course, 'semester'):
                try:
                    dean_qs = dean_qs.filter(semester=int(semester))
                except (ValueError, TypeError):
                    try:
                        dean_qs = dean_qs.filter(semester=semester)
                    except Exception:
                        pass
            # Filter by admission_year if model supports it (STRICT match when year provided)
            for year_field in ['admission_year', 'year', 'academic_year']:
                if hasattr(Course, year_field) and year not in (None, '', 0):
                    try:
                        dean_qs = dean_qs.filter(**{year_field: int(year)})
                    except Exception:
                        try:
                            dean_qs = dean_qs.filter(**{year_field: year})
                        except Exception:
                            pass
                    break
        except Exception as e:
            logger.exception("Error fetching dean courses: %s", e)
            dean_qs = Course.objects.none()

        logger.info("Dean queryset size for create_scheme: %d", dean_qs.count())
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
                # Get SchemeCourse model (may be imported dynamically)
                SchemeCourse = apps.get_model('hod', 'SchemeCourse')
                with transaction.atomic():
                    # Use update_or_create to avoid duplicates and ensure all rows are persisted
                    sc, created = SchemeCourse.objects.update_or_create(
                        branch=branch,
                        year=int(year),
                        semester=int(semester),
                        course_code=code,
                        defaults={
                            'course_title': title or '',
                            'l': int(l or 0),
                            't': int(t or 0),
                            'p': int(p or 0),
                            'total_hours': int(total_hours or 0),
                            'cie': int(cie or 0),
                            'see': int(see or 0),
                            'total_marks': int(total_marks or 0),
                            'credits': Decimal(str(credits)) if credits else Decimal('0.0'),
                            'category': category or '',
                            'is_elective': False,
                        }
                    )

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
        # Handle both regular and additional elective rows
        for section in ['pec', 'oec', 'esc', 'aec']:
            # Process regular elective rows
            j = 1
            while True:
                code = (request.POST.get(f'{section}_code_{j}', '') or '').strip()
                title = (request.POST.get(f'{section}_title_{j}', '') or '').strip()
                if not code and not title:
                    break
                faculty_id = request.POST.get(f'{section}_faculty_{j}') or None

                try:
                    # Get SchemeCourse model (may be imported dynamically)
                    SchemeCourse = apps.get_model('hod', 'SchemeCourse')
                    with transaction.atomic():
                        # Use update_or_create to avoid duplicates and ensure all elective rows are persisted
                        sc, created = SchemeCourse.objects.update_or_create(
                            branch=branch,
                            year=int(year),
                            semester=int(semester),
                            course_code=code,
                            defaults={
                                'course_title': title or '',
                                'category': section.upper(),
                                'is_elective': True,
                            }
                        )

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
            
            # Process additional elective rows (additional_pec_code_1, etc.)
            j_add = 1
            while True:
                code = (request.POST.get(f'additional_{section}_code_{j_add}', '') or '').strip()
                title = (request.POST.get(f'additional_{section}_title_{j_add}', '') or '').strip()
                if not code and not title:
                    break
                faculty_id = request.POST.get(f'additional_{section}_faculty_{j_add}') or None

                try:
                    SchemeCourse = apps.get_model('hod', 'SchemeCourse')
                    with transaction.atomic():
                        sc, created = SchemeCourse.objects.update_or_create(
                            branch=branch,
                            year=int(year),
                            semester=int(semester),
                            course_code=code,
                            defaults={
                                'course_title': title or '',
                                'category': section.upper(),
                                'is_elective': True,
                            }
                        )

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
                                logger.warning("Faculty user id=%s not found for additional elective %s.", faculty_id, code)

                        created_count += 1
                except Exception as e:
                    logger.exception("Failed to save additional elective %s row %s: %s", section, j_add, e)
                j_add += 1

        # messages & redirect
        # Only show "No rows were created" if we actually tried to process rows but none were valid
        # Check if any rows were submitted (not just dean courses)
        has_submitted_rows = False
        # Check main rows
        i_check = 1
        while True:
            code = (request.POST.get(f'code_new_{i_check}', '') or '').strip()
            title = (request.POST.get(f'title_new_{i_check}', '') or '').strip()
            if code or title:
                has_submitted_rows = True
                break
            i_check += 1
            if i_check > 100:  # safety limit
                break
        # Check elective rows
        if not has_submitted_rows:
            for section in ['pec', 'oec', 'esc', 'aec']:
                j_check = 1
                while True:
                    code = (request.POST.get(f'{section}_code_{j_check}', '') or '').strip()
                    title = (request.POST.get(f'{section}_title_{j_check}', '') or '').strip()
                    if code or title:
                        has_submitted_rows = True
                        break
                    j_check += 1
                    if j_check > 10:  # safety limit
                        break
                if has_submitted_rows:
                    break
        
        if created_count > 0:
            messages.success(request, f"Scheme saved successfully! ({created_count} rows created). CourseAllocation/FacultyAssignment should be created for HOD.")
        elif has_submitted_rows:
            # Rows were submitted but none were valid/saved
            messages.warning(request, "No valid rows were created. Please check that course codes and titles are provided.")
        # If no rows submitted at all, don't show any message (user might just be viewing the page)

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
