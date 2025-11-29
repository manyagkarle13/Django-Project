# MCE Syllabus Maker for Faculty — Project Report

## Abstract

Preparing a syllabus book is a tedious, time-consuming, and repetitive task for faculty and departments. Traditionally, it takes several weeks to manually type, format, and compile course syllabi into a single official PDF. To address this, **MCE Syllabus Maker for Faculty** is a Django-based web application that allows faculty and HODs to log in from a single unified portal using Faculty ID or Email ID, enter syllabus details via structured forms, auto-format them into the official college style, store them in a database for reuse, and generate both single-course syllabi and full department syllabus books (with cover pages, scheme tables, and preface). This eliminates duplication, ensures consistency, and significantly reduces manual effort.

---

## Problem Statement

Current syllabus preparation suffers from:

- Manual & time-consuming processes
- Inconsistent formatting across faculty
- Difficulty consolidating multiple syllabi into one official document
- Lack of centralized, reusable storage for syllabus content

This project addresses those issues by providing a unified, structured, and automated workflow.

---

## Proposed Solution (Detailed)

The application digitizes the syllabus creation workflow and provides:

1. Unified Login for Faculty & HOD

   - Single login page for all users (Faculty ID or Email ID).
   - Role (HOD/Faculty) is determined from the user profile in the database after authentication.

2. Dynamic Syllabus Entry Forms

   - Structured forms to capture every part of the syllabus, including:
     - Course Info: Title, Code, L-T-P, Hours/Week, Credits
     - Objectives
     - Outcomes (COs) — minimum 4, mapped to POs/PSOs
     - Modules: Module number, hours, topics
     - CIE & SEE schemes
     - Activities (if no lab) and Lab experiments (if applicable)
     - Books, E-Books (with links), MOOC courses
     - Assessment rubrics

3. Storage and Reuse

   - Syllabus data stored in a relational database (PostgreSQL/MySQL). Flexible data (modules, resources) can be stored as JSON fields for easy reuse.

4. Auto-Formatting Assistant

   - Generates output in the official college style so faculty only need to provide content.

5. Export Options

   - Export individual syllabi as PDF or DOCX.
   - Generate a Master Syllabus Book (title page, preface, scheme tables, and all combined syllabi).

6. Search and Reuse

   - Search past syllabi and reuse sections (books, modules, MOOCs).

7. Optional Analytics Dashboard

   - Track progress, visualize distributions and commonly used resources.

---

## Software & Tools

- Backend: Django (Python)
- Frontend: HTML5, CSS3, (Bootstrap 5 recommended)
- Database: PostgreSQL or MySQL (SQLite for prototyping)
- PDF Generation: WeasyPrint (note: system libs required)
- DOCX Export: python-docx
- Charts: Chart.js
- Version Control: Git / GitHub
- Deployment options: PythonAnywhere, Render, Railway.app, or a VPS

---

## Modules of the Project

1. Unified Authentication & Role Management
2. Course & Syllabus Management (forms, modules, COs, resources)
3. Database Storage with version history
4. Export Module (PDF/DOCX and Master Book)
5. Search & Reuse functionality
6. Analytics Dashboard (optional enhancement)

---

## How to Use (Operation Flow)

1. Faculty/HOD log in using Faculty ID or Email ID.
2. System identifies role (HOD/Faculty) from database profile.
3. Faculty selects assigned course or creates a new course, then enters syllabus details.
4. Save syllabus → Preview formatted view → Export as PDF/DOCX.
5. HOD/Faculty combines syllabi to generate Master Department Syllabus Book.

---

## How to Run (local development)

Open a PowerShell terminal in the project root (where `manage.py` is located) and run:

```powershell
# activate virtual environment (Windows)
.\syllabusmaker\Scripts\Activate.ps1

# install dependencies if needed
pip install -r requirements.txt

# apply migrations
python manage.py migrate

# create a superuser (optional)
python manage.py createsuperuser

# run the development server
python manage.py runserver
```

Then open http://127.0.0.1:8000/ in your browser.

Notes:
- If you use WeasyPrint for PDF generation, install its system dependencies (Cairo, Pango, GDK-PixBuf) on your OS before using it. On Windows, follow WeasyPrint docs for prerequisites.

---

## Problems Overcome

- Eliminates manual formatting and long compilation times.
- Centralized storage for reuse.
- Fast generation of official-format PDFs and Master Books.

---

## Future Enhancements

- AI suggestions for COs and book recommendations.
- Mobile app companion.
- Integration with college ERP.
- Collaborative editing with approval workflows.

---

## Next Steps I can help with

- Convert this Markdown to a printable PDF or a nicely styled HTML report.
- Add a formal cover page template and college branding to the site templates.
- Implement the database models and basic CRUD views/forms for courses, COs, modules, and resources.
- Wire up WeasyPrint to generate PDF output for individual courses and the master book.

If you want, tell me which step you'd like me to implement first and I will start making the code changes and add tests.
