import logging
import io
import os
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.apps import apps
from django.db.models import Q

from .models import (
    CollegeLevelCourse,
    SemesterCredit,
    Branch,
    Syllabus,
    Subject,
    Scheme,
)

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Helper: Soft Delete (improved)
# -------------------------------------------------------------------------
def _get_deleted_flag_name(model_cls):
    """Return the boolean deletion field name for model class (or None)."""
    for candidate in ("is_deleted", "deleted", "is_removed", "removed"):
        if candidate in [f.name for f in model_cls._meta.get_fields()]:
            return candidate
    return None


def _set_deleted_flag(obj, deleted=True):
    """
    Set a soft-delete flag and timestamp.
    Supports models that use either `is_deleted` (bool) or `deleted` (bool).
    Also updates `deleted_at` if present.
    """
    if obj is None:
        return

    # prefer canonical names if they exist
    if hasattr(obj, "is_deleted"):
        try:
            obj.is_deleted = bool(deleted)
        except Exception:
            logger.exception("Failed to set is_deleted on %r", obj)
    elif hasattr(obj, "deleted"):
        try:
            obj.deleted = bool(deleted)
        except Exception:
            logger.exception("Failed to set deleted on %r", obj)
    else:
        # fallback: try common alternatives
        for name in ("is_removed", "removed", "is_deleted_flag"):
            if hasattr(obj, name):
                try:
                    setattr(obj, name, bool(deleted))
                except Exception:
                    logger.exception("Failed to set %s on %r", name, obj)
                break

    # set / clear deleted_at if available
    if deleted and hasattr(obj, "deleted_at"):
        try:
            obj.deleted_at = timezone.now()
        except Exception:
            logger.exception("Failed to set deleted_at on %r", obj)
    elif not deleted and hasattr(obj, "deleted_at"):
        try:
            obj.deleted_at = None
        except Exception:
            logger.exception("Failed to clear deleted_at on %r", obj)

    try:
        obj.save()
    except Exception:
        logger.exception("Failed to save deletion flag on %r", obj)


# -------------------------------------------------------------------------
# PDF generators (reportlab) -- unchanged except single-copy
# -------------------------------------------------------------------------
def generate_syllabus_pdf_buffer(syllabus: Syllabus) -> io.BytesIO:
    """Generate PDF syllabus in exact MCE format matching the template."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
    from reportlab.lib import colors
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.4*inch, bottomMargin=0.4*inch, leftMargin=0.4*inch, rightMargin=0.4*inch)
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=11,
        textColor=colors.black,
        alignment=1,  # center
        spaceAfter=2,
    )
    
    college_style = ParagraphStyle(
        'College',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.black,
        alignment=1,
        spaceAfter=1,
    )
    
    section_heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=colors.black,
        spaceAfter=6,
        spaceBefore=6,
    )
    
    normal_style = ParagraphStyle(
        'Normal2',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
    )
    
    elements = []
    course = syllabus.course
    branch_name = getattr(course, 'branch', None)
    branch_name = branch_name.name.upper() if branch_name else "ENGINEERING"
    
    # ===== LOGO =====
    try:
        logo_path = os.path.join(settings.BASE_DIR, 'users/static/images/malnad_college_of_engineering_logo.jpeg')
        if os.path.exists(logo_path):
            logo = Image(logo_path, width=0.8*inch, height=0.8*inch)
            logo.hAlign = 'CENTER'
            elements.append(logo)
            elements.append(Spacer(1, 0.05*inch))
    except Exception as e:
        logger.debug("Logo not found: %s", e)
    
    # ===== COLLEGE HEADER (Centered) =====
    elements.append(Paragraph("MALNAD COLLEGE OF ENGINEERING, HASSAN", title_style))
    elements.append(Paragraph("(An Autonomous Institution Affiliated to VTU, Belgaum)", college_style))
    elements.append(Paragraph(f"DEPARTMENT OF {branch_name}", college_style))
    elements.append(Spacer(1, 0.1*inch))
    
    # ===== COURSE HEADER TABLE =====
    header_table_data = [
        ['Course Title', course.course_title, '', ''],
        ['Course Code', course.course_code, '(L-T-P)C', f"({course.teaching_hours_L or 0}-{course.teaching_hours_T or 0}-{course.teaching_hours_P or 0}) {course.credits or 0}"],
        ['Exam', '3 Hrs.', 'Hours/Week', str((course.teaching_hours_L or 0) + (course.teaching_hours_T or 0) + (course.teaching_hours_P or 0))],
        ['SEE', str(syllabus.see_scheme or course.see_marks or '') + ' Marks', 'Total Hours', f"{(course.teaching_hours_L or 0)*9}L+{(course.teaching_hours_P or 0)*14}P"],
    ]
    
    header_table = Table(header_table_data, colWidths=[1.2*inch, 2.2*inch, 1.2*inch, 2.2*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f5f5f5')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('BORDER', (0, 0), (-1, -1), 0.5, colors.black),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.15*inch))
    
    # ===== COURSE OBJECTIVES =====
    if syllabus.objectives:
        elements.append(Paragraph("Course Objectives", section_heading_style))
        objectives_lines = str(syllabus.objectives).split('\n') if syllabus.objectives else []
        for line in objectives_lines:
            if line.strip():
                elements.append(Paragraph(f"• {line.strip()}", normal_style))
        elements.append(Spacer(1, 0.1*inch))
    
    # ===== COURSE OUTCOMES =====
    if syllabus.outcomes:
        elements.append(Paragraph("Course Outcomes", section_heading_style))
        outcomes_data = [['#', 'Course Outcomes', 'Mapping to POs', 'Mapping to PSOs']]
        outcomes_lines = str(syllabus.outcomes).split('\n') if syllabus.outcomes else []
        for i, outcome in enumerate(outcomes_lines, 1):
            if outcome.strip():
                outcomes_data.append([str(i) + '.', outcome.strip(), '', ''])
        
        outcomes_table = Table(outcomes_data, colWidths=[0.5*inch, 3.8*inch, 1.1*inch, 1.1*inch])
        outcomes_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0c0c0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.black),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(outcomes_table)
        elements.append(Spacer(1, 0.1*inch))
    
    # ===== MODULE-WISE BREAKDOWN =====
    if syllabus.modules:
        elements.append(Paragraph("Module-wise Breakdown", section_heading_style))
        modules_data = [['Module', 'Details', 'Hrs']]
        modules_lines = str(syllabus.modules).split('\n') if syllabus.modules else []
        for i, module in enumerate(modules_lines, 1):
            if module.strip():
                modules_data.append([str(i), module.strip()[:60], ''])
        
        modules_table = Table(modules_data, colWidths=[0.6*inch, 5.2*inch, 0.6*inch])
        modules_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0c0c0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.black),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(modules_table)
        elements.append(Spacer(1, 0.1*inch))
    
    # ===== PRESCRIBED TEST BOOKS =====
    if syllabus.books:
        elements.append(Paragraph("Prescribed Test Books", section_heading_style))
        books_data = [['Sl No', 'Book Title', 'Authors', 'Edition', 'Publisher', 'Year']]
        books_lines = str(syllabus.books).split('\n') if syllabus.books else []
        for i, book in enumerate(books_lines, 1):
            if book.strip():
                books_data.append([str(i), book.strip(), '', '', '', ''])
        
        books_table = Table(books_data, colWidths=[0.5*inch, 2*inch, 1.5*inch, 0.8*inch, 1.5*inch, 0.5*inch])
        books_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0c0c0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.black),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(books_table)
        elements.append(Spacer(1, 0.1*inch))
    
    # ===== REFERENCE BOOKS =====
    if hasattr(syllabus, 'reference_books') and syllabus.reference_books:
        elements.append(Paragraph("Reference Books", section_heading_style))
        ref_books_data = [['Sl No', 'Book Title', 'Authors', 'Edition', 'Publisher', 'Year']]
        ref_books_lines = str(syllabus.reference_books).split('\n') if syllabus.reference_books else []
        for i, book in enumerate(ref_books_lines, 1):
            if book.strip():
                ref_books_data.append([str(i), book.strip(), '', '', '', ''])
        
        ref_books_table = Table(ref_books_data, colWidths=[0.5*inch, 2*inch, 1.5*inch, 0.8*inch, 1.5*inch, 0.5*inch])
        ref_books_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0c0c0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.black),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(ref_books_table)
        elements.append(Spacer(1, 0.1*inch))
    
    # ===== E-BOOKS & MOOCS =====
    if syllabus.ebooks or syllabus.moocs:
        elements.append(Paragraph("E-Resources", section_heading_style))
        
        if syllabus.ebooks:
            elements.append(Paragraph("<b>E-Books:</b>", normal_style))
            ebooks_list = str(syllabus.ebooks).split('\n') if syllabus.ebooks else []
            for ebook in ebooks_list:
                if ebook.strip():
                    elements.append(Paragraph(f"1. {ebook.strip()}", normal_style))
        
        if syllabus.moocs:
            elements.append(Paragraph("<b>MOOC Courses:</b>", normal_style))
            moocs_list = str(syllabus.moocs).split('\n') if syllabus.moocs else []
            for i, mooc in enumerate(moocs_list, 1):
                if mooc.strip():
                    elements.append(Paragraph(f"{i}. {mooc.strip()}", normal_style))
        
        elements.append(Spacer(1, 0.1*inch))
    
    # ===== PROPOSED ASSESSMENT PLAN =====
    if syllabus.cie_marks_data or syllabus.cie_scheme or syllabus.see_scheme:
        elements.append(Paragraph("Proposed Assessment Plan (for 50 marks of CIE):", section_heading_style))
        assessment_data = [['Tool', 'Remarks', 'Marks']]
        
        try:
            cie_val = int(syllabus.cie_scheme) if syllabus.cie_scheme else 50
        except:
            cie_val = 50
        
        # Parse and add assessment data from form if available
        if syllabus.cie_marks_data:
            try:
                import json
                cie_data = json.loads(syllabus.cie_marks_data) if isinstance(syllabus.cie_marks_data, str) else syllabus.cie_marks_data
                total_marks = 0
                for idx, item in enumerate(cie_data, 1):
                    tool = item.get('tool', '')
                    remarks = item.get('remarks', '')
                    marks = item.get('marks', '0')
                    if tool or remarks:
                        assessment_data.append([tool, remarks, str(marks)])
                        try:
                            total_marks += int(marks) if marks else 0
                        except:
                            pass
                if total_marks > 0:
                    assessment_data.append(['', 'Total', str(total_marks)])
                else:
                    assessment_data.append(['', 'Total', str(cie_val)])
            except:
                # Fallback to default data if parsing fails
                assessment_data.append(['Internals', 'Three tests conducted for 20 marks each and reduced to 10 marks', '30'])
                assessment_data.append(['AAT', 'Lab Evaluation', '20'])
                assessment_data.append(['', 'Total', str(cie_val)])
        else:
            # Default rows if no data
            assessment_data.append(['Internals', 'Three tests conducted for 20 marks each and reduced to 10 marks', '30'])
            assessment_data.append(['AAT', 'Lab Evaluation', '20'])
            assessment_data.append(['', 'Total', str(cie_val)])
        
        assessment_table = Table(assessment_data, colWidths=[1.5*inch, 4.5*inch, 1*inch])
        assessment_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0c0c0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.black),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(assessment_table)
        elements.append(Spacer(1, 0.1*inch))
    
    # ===== LABORATORY PLAN =====
    if syllabus.lab_work and (course.teaching_hours_P or 0) > 0:
        elements.append(Paragraph("Laboratory Plan", section_heading_style))
        lab_data = [['S.No', 'Program Details']]
        lab_lines = str(syllabus.lab_work).split('\n') if syllabus.lab_work else []
        for i, lab in enumerate(lab_lines, 1):
            if lab.strip():
                lab_data.append([str(i), lab.strip()])
        
        lab_table = Table(lab_data, colWidths=[0.7*inch, 5.9*inch])
        lab_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0c0c0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('BORDER', (0, 0), (-1, -1), 0.5, colors.black),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(lab_table)
        elements.append(Spacer(1, 0.1*inch))
    
    # ===== PAGE BREAK BEFORE ARTICULATION MATRIX =====
    elements.append(PageBreak())
    
    # ===== LOGO REPEAT =====
    try:
        logo_path = os.path.join(settings.BASE_DIR, 'users/static/images/malnad_college_of_engineering_logo.jpeg')
        if os.path.exists(logo_path):
            logo = Image(logo_path, width=0.8*inch, height=0.8*inch)
            logo.hAlign = 'CENTER'
            elements.append(logo)
            elements.append(Spacer(1, 0.05*inch))
    except Exception as e:
        logger.debug("Logo not found: %s", e)
    
    # ===== COLLEGE HEADER REPEAT (Centered) =====
    elements.append(Paragraph("MALNAD COLLEGE OF ENGINEERING, HASSAN", title_style))
    elements.append(Paragraph("(An Autonomous Institution Affiliated to VTU, Belgaum)", college_style))
    elements.append(Paragraph(f"DEPARTMENT OF {branch_name}", college_style))
    elements.append(Spacer(1, 0.1*inch))
    
    # ===== COURSE ARTICULATION MATRIX =====
    elements.append(Paragraph("Course Articulation Matrix", section_heading_style))
    
    # Create CO × PO/PSO matrix
    pos = ['PO1', 'PO2', 'PO3', 'PO4', 'PO5', 'PO6', 'PO7', 'PO8', 'PO9', 'PO10', 'PO11', 'PO12', 'PSO1', 'PSO2']
    outcomes_count = len([x for x in str(syllabus.outcomes).split('\n') if x.strip()]) if syllabus.outcomes else 4
    
    matrix_data = [['Course Outcomes'] + pos]
    for i in range(1, outcomes_count + 1):
        row = [f'CO{i}'] + ['' for _ in pos]
        matrix_data.append(row)
    
    col_width = 6.4 / len(pos)  # Distribute width among POs/PSOs
    matrix_table = Table(matrix_data, colWidths=[0.7*inch] + [col_width*inch] * len(pos))
    matrix_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c0c0c0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('BORDER', (0, 0), (-1, -1), 0.5, colors.black),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    elements.append(matrix_table)
    
    # Build PDF
    try:
        doc.build(elements)
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.exception("Error building PDF: %s", e)
        raise


def generate_course_pdf_buffer(course):
    """Generate PDF buffer for a single course syllabus."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from io import BytesIO
        import os
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()
        
        # Logo
        logo_path = os.path.join(settings.BASE_DIR, 'users/static/images/malnad_college_of_engineering_logo.jpeg')
        if os.path.exists(logo_path):
            logo = Image(logo_path, width=0.8*inch, height=0.8*inch)
            logo.hAlign = 'CENTER'
            elements.append(logo)
        
        elements.append(Spacer(1, 0.15*inch))
        
        # College Name
        college_style = ParagraphStyle(
            'CollegeName',
            parent=styles['Normal'],
            fontSize=14,
            textColor=colors.black,
            spaceAfter=6,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("MALNAD COLLEGE OF ENGINEERING", college_style))
        
        # Subtitle
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.black,
            spaceAfter=12,
            alignment=TA_CENTER
        )
        elements.append(Paragraph("An Autonomous Institution — Hassan, Karnataka", subtitle_style))
        
        # Divider line
        divider_data = [['_' * 80]]
        divider_table = Table(divider_data, colWidths=[7.5*inch])
        divider_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))
        elements.append(divider_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Title
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=12,
            textColor=colors.black,
            spaceAfter=16,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("COLLEGE LEVEL COURSE DETAILS", title_style))
        
        # Course Details Table
        details = [
            ['Course Code:', course.course_code or '—'],
            ['Course Title:', course.course_title or '—'],
            ['Course Category:', course.course_category or '—'],
            ['Department:', 'All Branches'],
            ['L - T - P:', f"{course.teaching_hours_L or 0} - {course.teaching_hours_T or 0} - {course.teaching_hours_P or 0}"],
            ['Credits:', str(course.credits or '0.0')],
            ['CIE / SEE Marks:', f"{course.cie_marks or 0} / {course.see_marks or 0}"],
        ]
        
        detail_table = Table(details, colWidths=[2*inch, 4.5*inch])
        detail_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(detail_table)
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        logger.exception("Error generating course PDF buffer: %s", e)
        return None


def generate_semester_credits_pdf(branch: Branch, academic_year: str, credits_dict: dict) -> io.BytesIO:
    """Generate semester credits PDF with logo and professional layout."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from io import BytesIO
        import os
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        elements = []
        styles = getSampleStyleSheet()
        
        # Logo
        logo_path = os.path.join(settings.BASE_DIR, 'users/static/images/malnad_college_of_engineering_logo.jpeg')
        if os.path.exists(logo_path):
            logo = Image(logo_path, width=0.8*inch, height=0.8*inch)
            logo.hAlign = 'CENTER'
            elements.append(logo)
        
        elements.append(Spacer(1, 0.15*inch))
        
        # College Name
        college_style = ParagraphStyle(
            'CollegeName',
            parent=styles['Normal'],
            fontSize=14,
            textColor=colors.black,
            spaceAfter=6,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("MALNAD COLLEGE OF ENGINEERING", college_style))
        
        # Subtitle
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.black,
            spaceAfter=12,
            alignment=TA_CENTER
        )
        elements.append(Paragraph("An Autonomous Institution — Hassan, Karnataka", subtitle_style))
        
        # Divider line
        divider_data = [['_' * 80]]
        divider_table = Table(divider_data, colWidths=[7.5*inch])
        divider_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))
        elements.append(divider_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Title
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=12,
            textColor=colors.black,
            spaceAfter=16,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        elements.append(Paragraph("SEMESTER CREDIT STRUCTURE", title_style))
        
        # Branch & Year Info
        info_data = [
            ['Branch:', getattr(branch, 'name', 'N/A')],
            ['Academic Year:', str(academic_year)],
        ]
        
        info_table = Table(info_data, colWidths=[1.5*inch, 5*inch])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Credits Table
        credits_data = [['Semester', 'Credits']]
        for sem in range(1, 9):
            cred = credits_dict.get(sem)
            if cred is not None:
                credits_data.append([f'Semester {sem}', str(cred)])
        
        credits_table = Table(credits_data, colWidths=[3*inch, 2*inch])
        credits_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f5f5f5')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(credits_table)
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        logger.exception("Error generating semester credits PDF: %s", e)
        return None


# -------------------------------------------------------------------------
# Dean views (dashboard, courses, semester credits, syllabus)
# -------------------------------------------------------------------------
@login_required
def dean_dashboard(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect("users:login")
    return render(request, "academics/dean_dashboard.html", {"user": request.user})


@login_required
def add_college_level_course(request):
    if request.method == "POST":
        action = request.POST.get("action")
        course_category = request.POST.get("course_type", "").strip()
        course_code = request.POST.get("code", "").strip()
        title = request.POST.get("title", "").strip()

        sem_raw = request.POST.get("semester", "").strip()
        semester = None
        if sem_raw != "":
            try:
                semester = int(sem_raw)
            except ValueError:
                semester = None

        try:
            l = int(request.POST.get("l") or 0)
            t = int(request.POST.get("t") or 0)
            p = int(request.POST.get("p") or 0)
            credits = float(request.POST.get("credits") or 0)
        except ValueError:
            messages.error(request, "Invalid numeric input for hours/credits.")
            return render(request, "academics/add_college_level_course.html")

        cie_marks = int(request.POST.get("cie_marks") or 50)
        see_marks = int(request.POST.get("see_marks") or 50)
        description = request.POST.get("description", "")

        course = CollegeLevelCourse.objects.create(
            department="All Branches",
            course_category=course_category,
            course_code=course_code,
            course_title=title,
            semester=semester,
            teaching_hours_L=l,
            teaching_hours_T=t,
            teaching_hours_P=p,
            cie_marks=cie_marks,
            see_marks=see_marks,
            credits=credits,
            description=description,
            added_by=request.user,
        )

        if action == "generate":
            pdf_buffer = generate_course_pdf_buffer(course)
            filename = f"{course.course_code}_details.pdf"
            pdf_buffer.seek(0)
            return FileResponse(pdf_buffer, as_attachment=True, filename=filename)

        messages.success(request, "Course saved successfully.")
        return redirect(reverse("academics:review_history"))

    return render(request, "academics/add_college_level_course.html")


@login_required
def edit_college_level_course(request, pk):
    course = get_object_or_404(CollegeLevelCourse, pk=pk)
    if request.method == "POST":
        course.course_category = request.POST.get("course_type", "").strip()
        course.course_code = request.POST.get("code", "").strip()
        course.course_title = request.POST.get("title", "").strip()

        sem_raw = request.POST.get("semester", "").strip()
        course.semester = int(sem_raw) if sem_raw != "" else None

        try:
            course.teaching_hours_L = int(request.POST.get("l") or 0)
            course.teaching_hours_T = int(request.POST.get("t") or 0)
            course.teaching_hours_P = int(request.POST.get("p") or 0)
            course.credits = float(request.POST.get("credits") or 0)
        except ValueError:
            messages.error(request, "Invalid numeric input for hours/credits.")
            return render(
                request,
                "academics/add_college_level_course.html",
                {"course": course, "editing": True},
            )

        course.cie_marks = int(request.POST.get("cie_marks") or 50)
        course.see_marks = int(request.POST.get("see_marks") or 50)
        course.description = request.POST.get("description", "")
        course.department = "All Branches"
        course.save()

        if request.POST.get("action") == "generate":
            buf = generate_course_pdf_buffer(course)
            buf.seek(0)
            filename = f"{course.course_code}_details.pdf"
            return FileResponse(buf, as_attachment=True, filename=filename)

        messages.success(request, "Course updated successfully.")
        return redirect(reverse("academics:review_history"))

    return render(request, "academics/add_college_level_course.html", {"course": course, "editing": True})


@login_required
def add_semester_credits(request):
    branches = Branch.objects.filter(active=True).order_by("code")
    if request.method == "POST":
        branch_id = request.POST.get("branch")
        admission_year = (request.POST.get("ar") or "").strip()
        action = request.POST.get("action")

        if not branch_id or not admission_year:
            messages.error(request, "Select branch and admission year.")
            return render(request, "academics/add_semester_credits.html", {"branches": branches, "range": range(1, 9)})

        branch = get_object_or_404(Branch, pk=branch_id)
        vals = {}
        for s in range(1, 9):
            key = f"sem_{s}"
            raw = (request.POST.get(key) or "").strip()
            if raw == "":
                continue
            try:
                vals[s] = float(raw)
            except ValueError:
                messages.warning(request, f"Invalid sem {s} value: {raw}, skipped.")
                continue

        sc, created = SemesterCredit.objects.get_or_create(branch=branch, admission_year=admission_year)
        for s in range(1, 9):
            if s in vals:
                setattr(sc, f"sem{s}", vals[s])
        sc.save()

        messages.success(request, f"Semester credits saved for {branch.code} ({admission_year}).")

        if action == "generate":
            try:
                pdf_buffer = generate_semester_credits_pdf(branch=branch, academic_year=admission_year, credits_dict=vals)
                filename = f"{branch.code}_{admission_year}_semester_credits.pdf"
                pdf_buffer.seek(0)
                return FileResponse(pdf_buffer, as_attachment=True, filename=filename)
            except Exception as e:
                logger.exception("PDF generation failed: %s", e)
                messages.error(request, "PDF generation failed.")

        return redirect(reverse("academics:dean_dashboard"))

    return render(request, "academics/add_semester_credits.html", {"branches": branches, "range": range(1, 9)})


@login_required
def edit_semester_credit(request, pk):
    sc = get_object_or_404(SemesterCredit, pk=pk)
    branches = Branch.objects.filter(active=True).order_by("code")
    if request.method == "POST":
        branch_id = request.POST.get("branch")
        admission_year = (request.POST.get("ar") or "").strip()
        action = request.POST.get("action")

        if not branch_id or not admission_year:
            messages.error(request, "Select branch and admission year.")
            return render(request, "academics/add_semester_credits.html", {"branches": branches, "editing_credit": sc, "range": range(1, 9)})

        branch = get_object_or_404(Branch, pk=branch_id)
        vals = {}
        for s in range(1, 9):
            key = f"sem_{s}"
            raw = (request.POST.get(key) or "").strip()
            if raw == "":
                setattr(sc, f"sem{s}", None)
                continue
            try:
                v = float(raw)
                vals[s] = v
                setattr(sc, f"sem{s}", v)
            except ValueError:
                messages.warning(request, f"Invalid sem {s} value: {raw}, skipped.")

        sc.branch = branch
        sc.admission_year = admission_year
        sc.save()
        messages.success(request, f"Semester credits updated for {branch.code} ({admission_year}).")

        if action == "generate":
            try:
                pdf_buffer = generate_semester_credits_pdf(branch=branch, academic_year=admission_year, credits_dict=vals)
                filename = f"{branch.code}_{admission_year}_semester_credits.pdf"
                pdf_buffer.seek(0)
                return FileResponse(pdf_buffer, as_attachment=True, filename=filename)
            except Exception as e:
                logger.exception("PDF generation failed: %s", e)
                messages.error(request, "PDF generation failed.")
                return redirect(reverse("academics:review_history"))

        return redirect(reverse("academics:review_history"))

    initial = {
        "branch": sc.branch.pk if getattr(sc, "branch", None) else "",
        "admission_year": getattr(sc, "admission_year", "") or "",
    }
    for i in range(1, 9):
        val = getattr(sc, f"sem{i}", "")
        if isinstance(val, (int, float)) and float(val).is_integer():
            val = int(val)
        initial[f"sem_{i}"] = val if val is not None else ""

    return render(
        request,
        "academics/add_semester_credits.html",
        {"branches": branches, "editing_credit": sc, "range": range(1, 9), "initial": initial},
    )


# -------------------------------------------------------------------------
# Syllabus listing & add/edit
# -------------------------------------------------------------------------
@login_required
def syllabus_list(request):
    courses = CollegeLevelCourse.objects.filter(is_deleted=False).order_by("course_code")

    # latest syllabus per course map
    syllabus_sem_map = {}
    qs = Syllabus.objects.filter(course__in=courses).order_by("course_id", "-created_on")
    for s in qs:
        if s.course_id not in syllabus_sem_map:
            syllabus_sem_map[s.course_id] = getattr(s, "semester", None)

    for c in courses:
        sem = getattr(c, "semester", None) or syllabus_sem_map.get(c.pk)
        if sem not in (None, "", 0):
            try:
                setattr(c, "display_semester", f"Sem {int(sem)}")
            except (ValueError, TypeError):
                c.display_semester = str(sem)
        else:
            c.display_semester = ""

    return render(request, "academics/add_syllabus_list.html", {"courses": courses})


@login_required
def add_syllabus(request, course_id):
    course = get_object_or_404(CollegeLevelCourse, pk=course_id)
    syllabus, created = Syllabus.objects.get_or_create(course=course)

    initial_sem = getattr(syllabus, "semester", None)
    if initial_sem in (None, "", 0):
        initial_sem = getattr(course, "semester", None)

    if request.method == "POST":
        import json
        action = request.POST.get("action", "").lower()

        # store big text fields (these names should match your form fields)
        syllabus.objectives = request.POST.get("objectives", "") or ""
        syllabus.outcomes = request.POST.get("outcomes", "") or ""
        syllabus.modules = request.POST.get("modules", "") or ""
        syllabus.cie_scheme = request.POST.get("cie", "") or request.POST.get("cie_scheme", "") or ""
        syllabus.see_scheme = request.POST.get("see", "") or request.POST.get("see_scheme", "") or ""
        syllabus.lab_work = request.POST.get("lab_work", "") or ""
        syllabus.books = request.POST.get("books", "") or ""
        syllabus.reference_books = request.POST.get("reference_books", "") or ""
        syllabus.ebooks = request.POST.get("ebooks", "") or ""
        syllabus.moocs = request.POST.get("moocs", "") or ""

        # Collect assessment data from form (Tool, Remarks, Marks)
        assessment_data = []
        idx = 1
        while f"tool_{idx}" in request.POST:
            tool = request.POST.get(f"tool_{idx}", "").strip()
            remarks = request.POST.get(f"remarks_{idx}", "").strip()
            marks = request.POST.get(f"marks_{idx}", "").strip()
            
            if tool or remarks or marks:
                assessment_data.append({
                    'tool': tool,
                    'remarks': remarks,
                    'marks': marks
                })
            idx += 1
        
        # Save assessment data as JSON if any exists
        if assessment_data:
            syllabus.cie_marks_data = json.dumps(assessment_data)
        else:
            syllabus.cie_marks_data = None

        posted_sem = request.POST.get("semester", "").strip()
        if posted_sem:
            try:
                syllabus.semester = int(posted_sem)
            except (ValueError, TypeError):
                syllabus.semester = None
        else:
            syllabus.semester = None

        try:
            syllabus.save()
        except Exception as e:
            logger.exception("Failed to save syllabus: %s", e)
            messages.error(request, "Failed to save syllabus.")
            return redirect(request.path)

        if action in ("generate", "generate_pdf"):
            try:
                buf = generate_syllabus_pdf_buffer(syllabus)
                buf.seek(0)
                filename = f"{course.course_code}_syllabus.pdf"
                return FileResponse(buf, as_attachment=True, filename=filename)
            except Exception as e:
                logger.exception("PDF generation failed: %s", e)
                messages.error(request, "PDF generation failed.")
                return redirect(request.path)

        messages.success(request, "Syllabus saved successfully.")
        return redirect(reverse("academics:syllabus_list"))

    return render(
        request,
        "academics/add_syllabus.html",
        {"course": course, "syllabus": syllabus, "initial_semester": initial_sem, "semesters": range(1, 9)},
    )


# backwards-compatible alias for older URL patterns
def add_or_edit_syllabus(request, course_id, *args, **kwargs):
    return add_syllabus(request, course_id, *args, **kwargs)


# -------------------------------------------------------------------------
# View / Download PDFs (single definitions)
# -------------------------------------------------------------------------
@login_required
def view_course_pdf(request, pk):
    course = get_object_or_404(CollegeLevelCourse, pk=pk)
    filename = f"{course.course_code}_details.pdf"
    try:
        buf = generate_course_pdf_buffer(course)
        buf.seek(0)
        resp = FileResponse(buf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{filename}"'
        return resp
    except Exception as e:
        logger.exception("view_course_pdf failed: %s", e)
        messages.error(request, "Unable to display PDF.")
        return redirect("academics:review_history")


@login_required
def download_course_pdf(request, pk):
    course = get_object_or_404(CollegeLevelCourse, pk=pk)
    filename = f"{course.course_code}_details.pdf"
    try:
        buf = generate_course_pdf_buffer(course)
        return FileResponse(buf, as_attachment=True, filename=filename)
    except Exception as e:
        logger.exception("download_course_pdf failed: %s", e)
        messages.error(request, "Unable to generate PDF.")
        return redirect("academics:review_history")


@login_required
def view_semester_credits_pdf(request, pk):
    sc = get_object_or_404(SemesterCredit, pk=pk)
    filename = f"{getattr(sc.branch, 'code', 'branch')}_{sc.admission_year}_credits.pdf"
    try:
        credits_dict = {i: getattr(sc, f"sem{i}") for i in range(1, 9) if getattr(sc, f"sem{i}", None) is not None}
        buf = generate_semester_credits_pdf(branch=sc.branch, academic_year=sc.admission_year, credits_dict=credits_dict)
        buf.seek(0)
        resp = FileResponse(buf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{filename}"'
        return resp
    except Exception as e:
        logger.exception("view_semester_credits_pdf failed: %s", e)
        messages.error(request, "Unable to display PDF.")
        return redirect("academics:review_history")


@login_required
def download_semester_credits_pdf(request, pk):
    sc = get_object_or_404(SemesterCredit, pk=pk)
    filename = f"{getattr(sc.branch, 'code', 'branch')}_{sc.admission_year}_credits.pdf"
    try:
        credits_dict = {i: getattr(sc, f"sem{i}") for i in range(1, 9) if getattr(sc, f"sem{i}", None) is not None}
        buf = generate_semester_credits_pdf(branch=sc.branch, academic_year=sc.admission_year, credits_dict=credits_dict)
        buf.seek(0)
        return FileResponse(buf, as_attachment=True, filename=filename)
    except Exception as e:
        logger.exception("download_semester_credits_pdf failed: %s", e)
        messages.error(request, "Unable to generate PDF.")
        return redirect("academics:review_history")


@login_required
def view_syllabus_pdf(request, pk):
    s = get_object_or_404(Syllabus, pk=pk)
    filename = f"{s.course.course_code}_syllabus.pdf"
    try:
        buf = generate_syllabus_pdf_buffer(s)
        buf.seek(0)
        resp = FileResponse(buf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{filename}"'
        return resp
    except Exception as e:
        logger.exception("view_syllabus_pdf failed: %s", e)
        messages.error(request, "Unable to display PDF.")
        return redirect("academics:review_history")


@login_required
def download_syllabus_pdf(request, pk):
    s = get_object_or_404(Syllabus, pk=pk)
    filename = f"{s.course.course_code}_syllabus.pdf"
    try:
        buf = generate_syllabus_pdf_buffer(s)
        buf.seek(0)
        return FileResponse(buf, as_attachment=True, filename=filename)
    except Exception as e:
        logger.exception("download_syllabus_pdf failed: %s", e)
        messages.error(request, "Unable to generate PDF.")
        return redirect("academics:review_history")


# -------------------------------------------------------------------------
# Review history + Soft-delete / restore / permanent delete handlers
# -------------------------------------------------------------------------
@login_required
def review_history(request):
    """Review history: Active & Recycle Bin."""
    show_deleted = request.GET.get("deleted", "0") == "1"

    # decide flag field name per model
    course_flag = _get_deleted_flag_name(CollegeLevelCourse) or "is_deleted"
    credit_flag = _get_deleted_flag_name(SemesterCredit) or "deleted"
    syllabus_flag = _get_deleted_flag_name(Syllabus) or "deleted"

    if show_deleted:
        courses = CollegeLevelCourse.objects.filter(**{course_flag: True}).order_by("-deleted_at")
        credits = SemesterCredit.objects.filter(**{credit_flag: True}).order_by("-id")
        syllabi = Syllabus.objects.filter(**{syllabus_flag: True}).order_by("-deleted_at")
    else:
        courses = CollegeLevelCourse.objects.filter(**{course_flag: False}).order_by("course_code")
        credits = SemesterCredit.objects.filter(**{credit_flag: False}).order_by("-id")
        syllabi = Syllabus.objects.filter(**{syllabus_flag: False}).order_by("-created_on")

    # Build a map course_id -> latest syllabus.semester (best-effort)
    syllabus_map = {}
    latest_syllabi = (
        Syllabus.objects.filter(course__in=courses)
        .order_by("course_id", "-created_on")
        .select_related("course")
    )
    for s in latest_syllabi:
        if s.course_id not in syllabus_map:
            syllabus_map[s.course_id] = getattr(s, "semester", None)

    # For each course determine a human-friendly display_semester
    for c in courses:
        sem = getattr(c, "semester", None) or syllabus_map.get(c.pk)
        display = ""
        if sem not in (None, "", 0):
            try:
                display = f"Sem {int(sem)}"
            except (ValueError, TypeError):
                display = str(sem)
        setattr(c, "display_semester", display)

    # Also set display_semester for syllabi listing
    for s in syllabi:
        sem = getattr(s, "semester", None)
        if not sem:
            sem = getattr(s.course, "semester", None) or syllabus_map.get(getattr(s.course, "pk", None))
        display = ""
        if sem not in (None, "", 0):
            try:
                display = f"Sem {int(sem)}"
            except (ValueError, TypeError):
                display = str(sem)
        setattr(s, "display_semester", display)

    return render(request, "academics/review_history.html", {
        "courses": courses,
        "credits": credits,
        "syllabi": syllabi,
        "show_deleted": show_deleted,
    })


# Course delete/restore/permanent-delete
@login_required
def delete_course_pdf(request, pk):
    course = get_object_or_404(CollegeLevelCourse, pk=pk)
    _set_deleted_flag(course, deleted=True)
    messages.success(request, "Course moved to recycle bin.")
    return redirect(reverse("academics:review_history") + "?deleted=0")


@login_required
def restore_course_pdf(request, pk):
    course = get_object_or_404(CollegeLevelCourse, pk=pk)
    _set_deleted_flag(course, deleted=False)
    messages.success(request, "Course restored.")
    return redirect(reverse("academics:review_history") + "?deleted=0")


@login_required
def permanent_delete_course_pdf(request, pk):
    course = get_object_or_404(CollegeLevelCourse, pk=pk)
    course.delete()
    messages.success(request, "Course permanently deleted.")
    return redirect(reverse("academics:review_history") + "?deleted=1")


# SemesterCredit delete/restore/permanent-delete
@login_required
def delete_credit_pdf(request, pk):
    sc = get_object_or_404(SemesterCredit, pk=pk)
    _set_deleted_flag(sc, deleted=True)
    messages.success(request, "Semester credit moved to recycle bin.")
    return redirect(reverse("academics:review_history") + "?deleted=0")


@login_required
def restore_credit_pdf(request, pk):
    sc = get_object_or_404(SemesterCredit, pk=pk)
    _set_deleted_flag(sc, deleted=False)
    messages.success(request, "Semester credit restored.")
    return redirect(reverse("academics:review_history") + "?deleted=0")


@login_required
def permanent_delete_credit_pdf(request, pk):
    sc = get_object_or_404(SemesterCredit, pk=pk)
    sc.delete()
    messages.success(request, "Semester credit permanently deleted.")
    return redirect(reverse("academics:review_history") + "?deleted=1")


# Syllabus delete/restore/permanent-delete
@login_required
def delete_syllabus(request, pk):
    """Soft-delete a Syllabus (move to recycle bin)."""
    s = get_object_or_404(Syllabus, pk=pk)
    _set_deleted_flag(s, deleted=True)
    messages.success(request, "Syllabus moved to recycle bin.")
    return redirect(reverse("academics:review_history") + "?deleted=0")


@login_required
def restore_syllabus(request, pk):
    """Restore a soft-deleted Syllabus back to active."""
    s = get_object_or_404(Syllabus, pk=pk)
    _set_deleted_flag(s, deleted=False)
    messages.success(request, "Syllabus restored.")
    return redirect(reverse("academics:review_history") + "?deleted=1")


@login_required
def permanent_delete_syllabus(request, pk):
    """Permanently delete a Syllabus from DB/files."""
    s = get_object_or_404(Syllabus, pk=pk)
    s.delete()
    messages.success(request, "Syllabus permanently deleted.")
    return redirect(reverse("academics:review_history") + "?deleted=1")


# -------------------------------------------------------------------------
# Optional management: purge permanently (not called automatically here)
# -------------------------------------------------------------------------
def purge_old_deleted(days: int = 30):
    cutoff = timezone.now() - timedelta(days=days)
    SemesterCredit.objects.filter(is_deleted=True, deleted_at__lte=cutoff).delete()
    Syllabus.objects.filter(is_deleted=True, deleted_at__lte=cutoff).delete()
    CollegeLevelCourse.objects.filter(is_deleted=True, deleted_at__lte=cutoff).delete()


@login_required
def redirect_to_latest_syllabus_for_course(request, course_pk):
    """Find the latest Syllabus for course_pk and redirect to its PDF viewer."""
    try:
        Syllabus = apps.get_model('academics', 'Syllabus')
        
        # Detect the date field name
        syllabus_fields = [f.name for f in Syllabus._meta.get_fields()]
        order_field = '-created_on' if 'created_on' in syllabus_fields else '-created_at'
        
        s = Syllabus.objects.filter(course_id=course_pk).order_by(order_field).first()
        if s:
            return redirect(reverse('academics:view_syllabus_pdf', args=[s.pk]))
    except Exception as e:
        logger.exception("Error finding latest syllabus for course %s: %s", course_pk, e)
    
    # fallback: go back to previous page
    messages.info(request, "No syllabus found for that course.")
    return redirect(request.META.get('HTTP_REFERER', '/'))
