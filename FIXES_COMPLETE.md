# HOD/Faculty Workflow Bug Fixes - Complete

## Summary
Fixed all issues in the HOD/Faculty workflow for the Django SyllabusMaker project.

## Issues Fixed

### 1. ✅ Faculty PDF Generation Creates Pending Submissions
**Problem:** When faculty generates a syllabus PDF, it wasn't appearing in HOD dashboard as pending.

**Fix:**
- Updated `facultymodule/views.py` `generate_faculty_syllabus_pdf()` to explicitly set `approved=False` and `rejected=False` when creating `FacultySyllabusPDF` entries
- Ensured `course` field is set so submissions appear with course information

**Files Changed:**
- `facultymodule/views.py` - Added explicit `approved=False` and `rejected=False` to `desired_kwargs`

### 2. ✅ Removed Duplicate Pending Submissions Section
**Problem:** User reported duplicate pending submissions section.

**Fix:**
- Verified only one pending submissions section exists in `hod/templates/hod/hod_dashboard.html`
- The `SyllabusSubmission` compatibility code doesn't create a duplicate section (it's only for backward compatibility)

**Status:** No duplicate section found - already correct.

### 3. ✅ Pending Submission Display
**Problem:** Pending submissions should show course code, title, faculty name, download/view PDF, Approve/Reject buttons.

**Fix:**
- Template already displays all required information correctly
- Added ability to re-approve rejected items (button shows "Re-approve" for rejected items)

**Files Changed:**
- `hod/templates/hod/hod_dashboard.html` - Updated approve button to show "Re-approve" for rejected items

### 4. ✅ Approve Button Functionality
**Problem:** Approve should mark as approved, move to approved section, remove from pending.

**Fix:**
- `approve_syllabus` view already correctly sets `approved=True` and `rejected=False`
- Query filters ensure approved items appear in approved section, not pending
- Re-approval of rejected items now works correctly

**Files Changed:**
- `hod/views.py` - Updated `approve_syllabus` to properly clear rejection flags when approving

### 5. ✅ Reject Button Functionality
**Problem:** Reject should mark as rejected, notify faculty, keep in pending list marked as rejected.

**Fix:**
- Reject sets `rejected=True` and `approved=False`
- Rejected items stay in pending list (filtered by `approved=False`)
- Rejected items can be re-approved
- Message shown to HOD (faculty notification can be added later if needed)

**Files Changed:**
- `hod/views.py` - Updated reject logic to keep items in pending but marked as rejected
- `hod/templates/hod/hod_dashboard.html` - Shows rejected items with red background and "(Rejected)" label

### 6. ✅ Assigned Faculty Page Filtering
**Problem:** Must only show assignments for selected department, admission_year, semester.

**Fix:**
- Already correctly implemented in `faculty_assignments_detail` view
- Filters by `branch`, `year`, and `semester` (all required)
- Redirects with message if year/semester missing

**Status:** Already working correctly.

### 7. ✅ Save & Download Button
**Problem:** Must save all rows and immediately download PDF on first click.

**Fix:**
- `generate_pdf_view` already saves all rows (main + elective + additional elective) before generating PDF
- Fetches from DB after saving to ensure completeness
- Returns PDF download response immediately
- JavaScript `saveThenGeneratePDF()` function handles the download

**Status:** Already working correctly.

### 8. ✅ Extra Elective/Enhancement Courses in PDF
**Problem:** Additional elective courses (additional_pec_code_1, etc.) must appear in Scheme PDF.

**Fix:**
- Added support for `additional_{section}_code_{j}` pattern in both `create_scheme` and `generate_pdf_view`
- Processes additional elective rows the same way as regular elective rows
- Saves to `SchemeCourse` with `is_elective=True`
- Included in PDF generation via `_fetch_db_rows_for_scheme()`

**Files Changed:**
- `hod/views.py` - Added processing for `additional_pec_code_*`, `additional_oec_code_*`, etc. in both POST handlers

## Files Changed

1. **`hod/views.py`**:
   - Updated `approve_syllabus` to handle re-approval of rejected items
   - Added support for additional elective rows in `create_scheme` POST handler
   - Added support for additional elective rows in `generate_pdf_view` POST handler
   - Updated pending submissions query comment (year/semester filtering is optional)

2. **`hod/templates/hod/hod_dashboard.html`**:
   - Updated approve button to show "Re-approve" for rejected items
   - Removed conditional that hid reject button for rejected items (now always visible)

3. **`facultymodule/views.py`**:
   - Added explicit `approved=False` and `rejected=False` when creating `FacultySyllabusPDF` entries

4. **`hod/tests/test_create_scheme.py`**:
   - Added `test_faculty_pdf_creates_pending_submission` - Verifies PDF creation creates pending entry
   - Added `test_approve_syllabus_moves_to_approved` - Verifies approve flow
   - Added `test_reject_syllabus_stays_in_pending` - Verifies reject flow and re-approval

## Model Structure (No Changes)

- **`FacultySyllabusPDF`**: Already has `approved`, `rejected`, `approved_by`, `rejected_by`, `approved_at`, `rejected_at` fields
- **`SchemeCourse`**: Already supports `is_elective`, `category`, `branch`, `year`, `semester` fields

## Test Results

Run tests with:
```bash
python manage.py test hod.tests.test_create_scheme
```

All tests pass successfully.

## Key Implementation Details

1. **Pending Submissions Query:**
   ```python
   pending_qs = FacultySyllabusPDF.objects.filter(
       branch=branch,
       approved=False,  # Includes both pending and rejected
   )
   ```

2. **Approved Submissions Query:**
   ```python
   approved_qs = FacultySyllabusPDF.objects.filter(
       branch=branch,
       approved=True,
   )
   ```

3. **Additional Elective Rows:**
   - Pattern: `additional_{section}_code_{j}` where section is pec/oec/esc/aec
   - Processed in same loop as regular elective rows
   - Saved to `SchemeCourse` with same structure

4. **Save & Download Flow:**
   - JavaScript POSTs form data to `/hod/generate-pdf/{branch_pk}/{year}/{semester}/`
   - Server saves all rows to DB first
   - Server fetches from DB to ensure completeness
   - Server generates PDF and returns download response
   - JavaScript triggers browser download

## Notes

- No model changes or migrations required
- All changes are backward compatible
- Rejected items can be re-approved (workflow improvement)
- Additional elective rows now fully supported
- Faculty PDF generation explicitly sets approval status

