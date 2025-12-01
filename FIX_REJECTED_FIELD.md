# Fix: Missing `rejected` Column in FacultySyllabusPDF

## Problem
- Visiting `/hod/dashboard/<dept_id>/?year=2025&semester=3` raised:
  `OperationalError: no such column: hod_facultysyllabuspdf.rejected`
- Template accessed `s.rejected` but the database column didn't exist

## Root Cause
- Model `FacultySyllabusPDF` had `rejected`, `rejected_at`, and `rejected_by` fields defined in `hod/models.py`
- Initial migration (`0001_initial.py`) did NOT include these fields
- Database schema was out of sync with model definition

## Solution

### 1. Created Migration
**File:** `hod/migrations/0004_add_rejected_fields_to_facultysyllabuspdf.py`

Added three fields to `FacultySyllabusPDF`:
- `rejected` (BooleanField, default=False)
- `rejected_at` (DateTimeField, null=True, blank=True)
- `rejected_by` (ForeignKey to User, null=True, blank=True)

### 2. Updated Template
**File:** `hod/templates/hod/hod_dashboard.html`

Changed from direct access:
```django
{% if s.rejected %}
```

To safe access with default:
```django
{% with is_rejected=s.rejected|default:False %}
  {% if is_rejected %}
```

This ensures the template works even if the field doesn't exist (defensive coding).

### 3. Verified Filtering
**Status:** Already correct

- **Dean Courses:** Filtered by `selected_year` and `selected_semester` (lines 532-548 in `hod/views.py`)
- **Pending Submissions:** Filtered by `selected_year` and `selected_semester` (lines 628-631 in `hod/views.py`)
- **Approved Submissions:** Filtered by `selected_year` and `selected_semester` (lines 647-650 in `hod/views.py`)

## Files Changed

1. **`hod/migrations/0004_add_rejected_fields_to_facultysyllabuspdf.py`** (NEW)
   - Migration to add `rejected`, `rejected_at`, `rejected_by` fields

2. **`hod/templates/hod/hod_dashboard.html`**
   - Updated to safely access `rejected` field using `{% with %}` and `|default:False`

## Migration Steps

Run:
```bash
python manage.py migrate hod
```

This will apply migration `0004_add_rejected_fields_to_facultysyllabuspdf` and add the missing columns.

## Testing

After migration, verify:
1. Dashboard loads without `OperationalError`
2. Pending submissions display correctly
3. Rejected items show with red background and "(Rejected)" label
4. Approve/Reject buttons work correctly
5. Filtering by year/semester works for all sections

## Schema Changes

**Added to `hod_facultysyllabuspdf` table:**
- `rejected` BOOLEAN DEFAULT 0
- `rejected_at` DATETIME NULL
- `rejected_by_id` INTEGER NULL (FK to auth_user)

No data loss - all fields are nullable or have defaults.

