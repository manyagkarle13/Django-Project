# Fix NameError and Include Dean-Assigned Courses in create_scheme View

## Problem
- **Error**: `NameError: name 'DeanCourse' is not defined`
- **Location**: `hod/views.py`, `create_scheme()` function around line 2577
- **URL**: `http://127.0.0.1:8000/hod/create-scheme/10/2025/3/`

## Root Cause
The code referenced `DeanCourse` which doesn't exist. The codebase uses `CollegeLevelCourse` from `academics.models` to represent dean-assigned courses. This model is imported at the top of `hod/views.py` as `Course`.

## Solution

### 1. Fixed NameError
**File**: `hod/views.py` (lines 2575-2588)

**Before:**
```python
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
```

**After:**
```python
# Build Dean course list (display only) - Include courses assigned by Dean for admission_year & sem in create scheme and in PDF
# Use CollegeLevelCourse (imported as Course) which represents dean-assigned courses
dean_courses = []
if Course is not None:
    try:
        # Filter by branch (college-wide courses have branch=None, branch-specific have branch=branch)
        dean_qs = Course.objects.filter(
            Q(branch__isnull=True) | Q(branch=branch),
            is_deleted=False  # Exclude deleted courses
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
    except Exception as e:
        logger.exception("Error fetching dean courses: %s", e)
        dean_qs = Course.objects.none()
```

### 2. Key Changes
- ✅ Replaced `DeanCourse` with `Course` (which is `CollegeLevelCourse`)
- ✅ Added `is_deleted=False` filter to exclude deleted courses
- ✅ Improved error handling with logging
- ✅ Better type conversion for semester filtering

### 3. Dean Courses Already Included in PDF
The PDF generation already includes dean courses via:
- `_fetch_db_rows_for_scheme()` function (lines 341-379) - fetches dean courses
- `generate_pdf_view()` function (lines 943-1012) - includes dean courses in PDF
- `_build_scheme_pdf_bytes()` function (lines 113-339) - builds PDF with dean courses

No changes needed for PDF generation - it already works correctly.

## Testing

### Test File Created
**File**: `hod/tests/test_create_scheme.py`

Tests cover:
1. ✅ Dean courses are included in view context
2. ✅ Dean courses have all required fields
3. ✅ HTML response contains dean course titles
4. ✅ Filtering by semester works correctly
5. ✅ Deleted courses are excluded
6. ✅ College-wide courses (branch=None) are included
7. ✅ NameError is fixed

### Running Tests
```bash
python manage.py test hod.tests.test_create_scheme --verbosity=2
```

## Verification

### Django Check
```bash
python manage.py check
```
✅ **Result**: No errors

### Manual Testing Checklist
1. ✅ Navigate to `/hod/create-scheme/{branch_pk}/2025/3/`
2. ✅ Verify page loads without NameError
3. ✅ Verify dean-assigned courses appear in the form
4. ✅ Verify courses are filtered by semester (only semester 3 courses)
5. ✅ Verify deleted courses don't appear
6. ✅ Generate PDF and verify dean courses are included

## Files Modified

1. **hod/views.py**
   - Fixed `create_scheme()` function to use `Course` instead of `DeanCourse`
   - Added proper filtering and error handling

2. **hod/tests/test_create_scheme.py** (NEW)
   - Comprehensive test suite for `create_scheme` view

3. **hod/tests/__init__.py** (NEW)
   - Created to make tests directory a Python package

## Business Logic

**Rule**: "Include courses assigned by Dean for admission_year & sem in create scheme and in PDF"

- Dean-assigned courses are represented by `CollegeLevelCourse` model
- Courses are filtered by:
  - Branch: `branch=None` (college-wide) OR `branch=branch` (branch-specific)
  - Semester: `semester=semester` (if field exists)
  - Deleted status: `is_deleted=False`
- The `admission_year` parameter is used for the scheme document context, not for filtering courses (courses don't have an `admission_year` field)

## Commit Message
```
Fix NameError and include Dean-assigned courses in create_scheme view and generated PDF

- Replace undefined DeanCourse with CollegeLevelCourse (Course) in create_scheme view
- Add is_deleted filter to exclude deleted courses
- Improve error handling and logging
- Add comprehensive test suite for create_scheme view
- Verify PDF generation already includes dean courses (no changes needed)
```

## Summary

✅ **NameError Fixed**: Replaced `DeanCourse` with `Course` (CollegeLevelCourse)
✅ **Dean Courses Included**: View now correctly fetches and displays dean-assigned courses
✅ **PDF Generation**: Already includes dean courses (verified, no changes needed)
✅ **Tests Added**: Comprehensive test suite validates all functionality
✅ **Django Check**: Passes without errors

The fix is minimal, safe, and maintains backward compatibility while ensuring dean-assigned courses are properly displayed in both the HTML view and generated PDF.

