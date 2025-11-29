# MCE Syllabus Maker — AI Coding Agent Instructions

## Architecture Overview

This is a **multi-app Django 5.2 project** for digitizing syllabus creation workflows for Malnad College of Engineering. The system supports roles: HOD, Faculty, and Dean. Key flow: HODs manage course schemes → Faculty submit syllabi → PDFs generated with ReportLab.

### App Structure
- **`academics/`** — Core data models: `Branch`, `CollegeLevelCourse` (dean-created courses), `Syllabus`, `SemesterCredit`
- **`hod/`** — HOD views & PDF generation (`_build_complete_scheme_pdf`, `generate_pdf_view`); manages `SchemeDocument`, `CourseAllocation`, `FacultyAssignment`
- **`facultymodule/`** — Faculty dashboard: view assigned courses, submit syllabi
- **`users/`** — Custom authentication (`CustomUser` with role-based routing; email is USERNAME_FIELD)
- **`courses/`** — Legacy scheme/subject models (being superseded by `academics.Scheme`)

### Critical Pattern: Lazy Model Imports
Models are fetched dynamically via `apps.get_model()` throughout `hod/views.py` to handle model renames/deletions gracefully:

```python
try:
    CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
    # use model
except LookupError:
    logger.debug("Model not found")
    # fallback
except Exception as e:
    logger.exception("Unexpected error: %s", e)
```

**When to use:** Any view or utility that needs optional model access or cross-app imports. Direct imports at module level are used only for required models.

## Key Data Flows

### Scheme PDF Generation (`hod/views.py`)
1. **`generate_pdf_view()`** — Fetches dean courses (`CollegeLevelCourse`), merges with posted/DB rows, calls `_build_complete_scheme_pdf()`
2. **`_build_complete_scheme_pdf()`** — Generates 7-page PDF using ReportLab:
   - Pages 1–6: Cover, Vision/Mission, PEOs/POs, Evaluation schemes, Course types
   - Page 7+: Scheme table + electives, with green borders via custom `BorderedPageCanvas`
3. **Saves to `SchemeDocument`** model with soft-delete flag (`is_deleted=False`)

**Note:** Main/elective rows are passed as list of dicts (not ORM objects) for flexibility:
```python
{'code': 'CS101', 'title': '...', 'l': 2, 't': 1, 'p': 0, 'cie': 50, 'see': 50, 'credits': '4', 'faculty_name': 'Dr. X'}
```

### Faculty Assignment Workflow
- `CourseAllocation` (HOD allocates course code to branch)
- `FacultyAssignment` links `Faculty` to `CourseAllocation`
- Use `transaction.atomic()` when creating linked records (idempotent with `get_or_create` + `update_or_create`)

## Query Patterns & Pitfalls

### ✅ Correct ORM Usage
```python
# ✅ Use select_related for FK joins
sc_qs = SchemeCourse.objects.filter(scheme__branch_id=branch_id)
sc_qs = sc_qs.select_related('scheme', 'faculty').order_by('scheme__year', 'semester')

# ✅ Use Q objects for OR conditions
dean_qs = CollegeLevelCourse.objects.filter(Q(branch__isnull=True) | Q(branch=branch))

# ✅ Atomic transactions for multi-object operations
with transaction.atomic():
    for sc in sc_qs:
        ca, _ = CourseAllocation.objects.get_or_create(...)
        FacultyAssignment.objects.update_or_create(...)
```

### ❌ Common Mistakes (Fixed in Code)
- **Wrong field lookups:** `select_related('faculty')` on models without FK `faculty` → use `select_related('scheme')` instead
- **Missing related field prefix:** `order_by('year')` should be `order_by('scheme__year')` for cross-table fields
- **Not using transaction.atomic()** for cascading creates (can leave DB in inconsistent state)

## File Conventions

### URL Routing
- Route naming: `hod:<action>_<resource>`, e.g., `hod:generate_pdf_view`, `hod:download_scheme`
- Query params: `?year=2023&semester=3` for filtering

### Template Structure
- Base: `templates/base.html` (global layout)
- App templates: `templates/<app>/<view_name>.html`
- PDF generation: Handled in views, not templates

### Model Field Naming
- Teaching hours: `teaching_hours_L`, `teaching_hours_T`, `teaching_hours_P` (not `l_hours`, `t_hours`)
- Marks: `cie_marks`, `see_marks` (not `cie`, `see`)
- Soft delete: `is_deleted` boolean + `deleted_at` timestamp (used in `academics.CollegeLevelCourse`, `hod.SchemeDocument`)

### PDF Generation (ReportLab)
- Use `BytesIO()` buffer, return `buffer.getvalue()`
- Always use `doc.build(..., canvasmaker=BorderedPageCanvas)` for styled pages
- Font: `Times-Roman` (body), `Times-Bold` (headers), `Helvetica-Bold` (table headers)
- Colors: Green `#008000` for borders, light blue `#8ADBE9` for table headers

## Authentication & Authorization

- **Custom User Model:** `users.CustomUser` (email-based, role-based routing in `CustomLoginView`)
- **HOD Assignment:** OneToOne link: `request.user.hod_assignment` → `branch`
- **Faculty Assignment:** Through `hod.Faculty` profile (OneToOne to CustomUser)
- **Decorators:** `@login_required` on all protected views; consider `@require_POST` for mutations

### Role-Based Redirects
```python
if hasattr(user, 'hod_assignment') and user.hod_assignment:
    return reverse_lazy('hod:dashboard_self', kwargs={'branch_pk': user.hod_assignment.branch.pk})
elif user.role == 'faculty':
    return reverse_lazy('facultymodule:faculty_dashboard')
```

## Logging & Error Handling

- **Logger setup:** `logger = logging.getLogger(__name__)` at module top
- **Pattern:** Log exceptions with context before redirecting:
  ```python
  except LookupError as e:
      logger.exception("Model not found: %s", e)
      messages.error(request, "Required models not found.")
      return redirect('hod:dashboard_redirect')
  ```
- **User-facing:** Use `messages.success()`, `messages.warning()`, `messages.error()`
- **Dev-facing:** Use `logger.debug()`, `logger.info()`, `logger.exception()`

## External Dependencies

- **ReportLab:** PDF generation (tables, paragraphs, images, canvas layers)
- **Django 5.2:** Latest LTS; supports Python 3.10+
- **psycopg2:** PostgreSQL driver (dev uses SQLite; production uses PostgreSQL)
- **WeasYPrint:** Alternative for CSS-based PDF (not currently used; ReportLab is primary)

## Testing & Debugging

- **No test suite present** — consider adding `tests/` with Django's `TestCase` for critical workflows
- **Django shell:** `python manage.py shell` to test model queries
- **Debug settings:** `DEBUG=True` in dev (insecure key in `settings.py` — rotate in production)
- **Database:** Run `python manage.py migrate` after model changes

## Development Workflow

1. **Model changes:** Create migration → update views → test queries with `select_related()`
2. **PDF changes:** Edit `_build_complete_scheme_pdf()` → test with `generate_pdf_view()` POST
3. **New app features:** Follow role-based redirect pattern (HOD/Faculty/Dean) in `CustomLoginView`
4. **Cross-app queries:** Always use `apps.get_model()` + `LookupError` try/catch for safety

## Quick Reference: Key Files

| File | Purpose |
|------|---------|
| `syllabus_maker/settings.py` | Django config; custom user model, installed apps, auth backends |
| `academics/models.py` | `Branch`, `CollegeLevelCourse`, `Syllabus`, `SemesterCredit` |
| `hod/models.py` | `SchemeDocument`, `CourseAllocation`, `FacultyAssignment`, `HODAssignment` |
| `hod/views.py` | PDF generation, scheme management, faculty assignment workflows |
| `users/models.py` | `CustomUser` (email-based, role field), `CustomUserManager` |
| `users/views.py` | `CustomLoginView` with role-based redirect logic |
| `facultymodule/views.py` | Faculty dashboard and syllabus submission |

---

**Last Updated:** November 28, 2025  
**Django Version:** 5.2.6  
**Python:** 3.10+
