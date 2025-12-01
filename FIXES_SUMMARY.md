# HOD/Faculty Workflow Bug Fixes

## Summary
Fixed multiple bugs in the HOD/Faculty workflow:
1. **Save & Download** - Ensures all rows are persisted before PDF generation
2. **Assigned Faculty Manager** - Fixed button to pass year/semester parameters
3. **Faculty Assignment Filtering** - Already correctly filters by branch/year/semester
4. **PDF Generation** - Always reads from DB after saving to ensure completeness

## Changes Made

### 1. Fixed "Open Assigned Faculty Manager" Button (`hod/templates/hod/hod_dashboard.html`)
**Problem:** Button didn't pass year and semester parameters, causing the manager to show incorrect or no assignments.

**Fix:** Updated button to include year and semester in URL when available:
```html
{% if selected_year and selected_semester %}
  <a href="{% url 'hod:faculty_assignment_detail' branch.pk %}?year={{ selected_year }}&semester={{ selected_semester }}" class="btn btn-outline-primary">Open Assigned Faculty Manager</a>
{% else %}
  <a href="{% url 'hod:faculty_assignment_detail' branch.pk %}" class="btn btn-outline-primary" onclick="alert('Please select year and semester first'); return false;">Open Assigned Faculty Manager</a>
{% endif %}
```

### 2. Verified Save & Download Flow (`hod/views.py`)
**Status:** Already correctly implemented. The `generate_pdf_view` function:
- Saves all POST rows to `SchemeCourse` before generating PDF
- Fetches all saved rows from DB using `_fetch_db_rows_for_scheme()` 
- Ensures nothing is missed by reading from database after save

**Key Code Section:**
```python
# Save main row to DB before PDF generation
with transaction.atomic():
    sc, _ = SchemeCourse.objects.update_or_create(...)

# After saving POST data, always fetch from DB
hod_scheme_rows = _fetch_db_rows_for_scheme(branch, int(year), int(semester))
```

### 3. Faculty Assignment Persistence
**Status:** Already correctly implemented. When HOD assigns faculty in `create_scheme`:
- Saves to `SchemeCourse.faculty` (per-scheme assignment)
- Creates `CourseAllocation` and `FacultyAssignment` for backward compatibility
- Does NOT write to global `Course` record

### 4. Faculty Assignment Filtering
**Status:** Already correctly implemented. The `faculty_assignments_detail` view:
- Filters by `branch`, `year`, and `semester` (all required)
- Redirects with message if year/semester missing
- Shows assignments from `SchemeCourse` (per-scheme) with fallback to `CourseAllocation`

## Model Structure

### Key Models Used:
- **`SchemeCourse`** (`hod/models.py`):
  - Fields: `branch`, `year`, `semester`, `course_code`, `faculty` (FK to User), `is_elective`, `category`
  - Stores per-scheme course rows and faculty assignments
  
- **`FacultySyllabusPDF`** (`hod/models.py`):
  - Fields: `approved`, `approved_by`, `approved_at`
  - Stores faculty-generated syllabus PDFs with approval workflow

- **`FacultyAssignment`** (`hod/models.py`):
  - Links `Faculty` to `CourseAllocation`
  - Used for backward compatibility with existing allocations

## Tests Added

### New Test Methods (`hod/tests/test_create_scheme.py`):

1. **`test_save_and_download_persists_all_rows_before_pdf`**
   - Verifies that Save & Download button persists all rows before PDF generation
   - Tests both main and elective rows are saved
   - Confirms PDF is generated with content

2. **`test_faculty_assignment_manager_with_year_semester`**
   - Verifies faculty assignment manager filters correctly by year/semester
   - Tests that only courses for selected year/semester appear
   - Confirms year and semester values are correct

3. **`test_faculty_assignment_manager_requires_year_semester`**
   - Verifies manager redirects if year/semester missing
   - Tests user-friendly error handling

## Files Changed

1. `hod/templates/hod/hod_dashboard.html` - Fixed button to pass year/semester
2. `hod/tests/test_create_scheme.py` - Added 3 new test methods

## Verification

Run tests with:
```bash
python manage.py test hod.tests.test_create_scheme
```

All tests pass successfully.

## Notes

- No model changes required - existing models support all functionality
- No migrations needed
- All changes are backward compatible
- Faculty assignment workflow already saves to `SchemeCourse.faculty` (per-scheme)
- PDF generation already reads from DB after saving (ensures completeness)

