# Comprehensive Fix: HOD Create Scheme, PDF Generation, and Faculty Assignments

## Summary
Fixed multiple issues in the HOD app related to create_scheme view, PDF generation, faculty assignments, and missing templates.

## Issues Fixed

### 1. ✅ NameError: DeanCourse (Already Fixed)
- **Status**: Already resolved in previous fix
- **Solution**: Replaced `DeanCourse` with `Course` (CollegeLevelCourse)
- **Location**: `hod/views.py` line 2575-2596

### 2. ✅ Elective Courses Missing in PDF
- **Problem**: Elective courses added in create_scheme form were not saved to DB before PDF generation
- **Solution**: Modified `generate_pdf_view()` to save elective courses to database before generating PDF
- **Location**: `hod/views.py` lines 1050-1125
- **Changes**:
  - Added code to save electives to `SchemeCourse` model before PDF generation
  - Creates/updates `CourseAllocation` and `FacultyAssignment` for electives
  - Merges DB electives with posted ones to avoid duplicates

### 3. ✅ Faculty Assignments Not Showing Scheme Courses
- **Problem**: Faculty assignments page wasn't properly filtering by branch, year, and semester
- **Solution**: Updated `faculty_assignments_detail()` to:
  - Check `SchemeCourse` model directly for `branch`, `year`, and `semester` fields (not just via `scheme__`)
  - Properly filter by branch (handles both FK and integer field)
  - Filter by year and semester from query params
- **Location**: `hod/views.py` lines 1792-1841

### 4. ✅ TemplateDoesNotExist: edit_semester_schema.html
- **Problem**: Template missing when clicking "Manage Schema"
- **Solution**: Created `hod/templates/hod/edit_semester_schema.html`
- **Features**:
  - Shows subjects for the selected semester
  - Links to create/edit scheme
  - Back to dashboard button
  - Clean, consistent UI matching existing templates

### 5. ✅ PDF Includes All Courses
- **Status**: Verified and enhanced
- **Solution**: 
  - PDF generation already includes dean courses via `_fetch_db_rows_for_scheme()`
  - Enhanced to merge posted electives with DB electives
  - Ensures no duplicates by course code

## Files Modified

1. **hod/views.py**
   - Fixed `generate_pdf_view()` to save electives before PDF generation (lines 1050-1125)
   - Fixed `faculty_assignments_detail()` filtering (lines 1792-1841)
   - Already fixed `create_scheme()` NameError (lines 2575-2596)

2. **hod/templates/hod/edit_semester_schema.html** (NEW)
   - Created missing template for edit_semester_schema view

3. **hod/tests/test_create_scheme.py**
   - Added test for PDF generation with electives
   - Added test for faculty assignments showing scheme courses

## Key Code Changes

### Elective Saving in PDF Generation
```python
# Save elective to DB before PDF generation to ensure it's included
try:
    SchemeCourse = apps.get_model('hod', 'SchemeCourse')
    with transaction.atomic():
        sc, created = SchemeCourse.objects.get_or_create(
            branch=branch_pk,
            year=int(year),
            semester=int(semester),
            course_code=code,
            defaults={...}
        )
        # Also create CourseAllocation and FacultyAssignment
        ...
except Exception as e:
    logger.exception("Error saving elective %s: %s", code, e)
```

### Faculty Assignments Filtering
```python
# Check SchemeCourse model directly for branch, year, semester
branch_lookups = ['scheme__branch', 'scheme__branch_id', 'scheme__branch__pk', 'branch', 'branch_id']
year_lookups = ['year', 'academic_year', 'scheme__year', ...]  # Check direct fields first
sem_lookups = ['semester', 'scheme__semester', ...]  # Check direct fields first
```

## Testing

### Test Cases Added
1. `test_pdf_generation_includes_dean_and_elective` - Verifies PDF includes both dean and elective courses
2. `test_faculty_assignments_show_scheme_courses` - Verifies faculty assignments page shows scheme courses with proper filtering

### Running Tests
```bash
python manage.py test hod.tests.test_create_scheme --verbosity=2
```

## Verification Checklist

- ✅ NameError fixed (DeanCourse -> Course)
- ✅ Dean courses appear in create_scheme HTML view
- ✅ Dean courses included in PDF
- ✅ Elective courses saved before PDF generation
- ✅ Elective courses appear in PDF
- ✅ Faculty assignments page filters by branch/year/semester
- ✅ Faculty assignments show scheme courses
- ✅ edit_semester_schema template exists and renders
- ✅ No linter errors

## Commit Message
```
Fix: include Dean-assigned & elective courses in create_scheme view and PDF; sync faculty assignment with scheme; restore edit_semester_schema template.

- Save elective courses to DB before PDF generation to ensure inclusion
- Fix faculty_assignments_detail to properly filter by branch/year/semester
- Create missing edit_semester_schema.html template
- Add tests for PDF generation and faculty assignments
- Enhance elective merging to avoid duplicates
```

## Notes

- All changes are backward compatible
- No database migrations required
- Uses existing model fields and relationships
- Error handling added for robustness
- Logging added for debugging

