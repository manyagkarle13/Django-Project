# Unified Diff Summary: Fix Missing `rejected` Column

## Problem
`OperationalError: no such column: hod_facultysyllabuspdf.rejected` when accessing HOD dashboard.

## Solution

### 1. Created Migration
**File:** `hod/migrations/0004_add_rejected_fields_to_facultysyllabuspdf.py` (NEW)

```python
# Generated manually to add rejected fields to FacultySyllabusPDF

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('hod', '0003_add_schemecourse_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='facultysyllabuspdf',
            name='rejected',
            field=models.BooleanField(default=False, help_text='Marked as rejected by HOD'),
        ),
        migrations.AddField(
            model_name='facultysyllabuspdf',
            name='rejected_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='facultysyllabuspdf',
            name='rejected_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='rejected_faculty_pdfs', to=settings.AUTH_USER_MODEL),
        ),
    ]
```

### 2. Updated Template
**File:** `hod/templates/hod/hod_dashboard.html`

**Changed:**
- Added `{% with is_rejected=s.rejected|default:False %}` to safely access the `rejected` field
- Wrapped template logic in `{% with %}` block to avoid errors if field doesn't exist
- Moved `{% endwith %}` to proper location after closing `</tr>`

**Before:**
```django
{% if s.rejected %}
  <span>(Rejected)</span>
{% endif %}
```

**After:**
```django
{% with is_rejected=s.rejected|default:False %}
  {% if is_rejected %}
    <span>(Rejected)</span>
  {% endif %}
{% endwith %}
```

### 3. Verified Filtering
**Status:** Already correct - no changes needed

- **Dean Courses:** Filtered by `selected_year` and `selected_semester` (lines 532-548)
- **Pending Submissions:** Filtered by `selected_year` and `selected_semester` (lines 628-631)
- **Approved Submissions:** Filtered by `selected_year` and `selected_semester` (lines 647-650)

## Schema Changes

**Added to `hod_facultysyllabuspdf` table:**
- `rejected` BOOLEAN NOT NULL DEFAULT 0
- `rejected_at` DATETIME NULL
- `rejected_by_id` INTEGER NULL (FK to auth_user)

## Migration Command

```bash
python manage.py migrate hod
```

## Files Changed

1. **`hod/migrations/0004_add_rejected_fields_to_facultysyllabuspdf.py`** (NEW)
   - Adds `rejected`, `rejected_at`, `rejected_by` fields

2. **`hod/templates/hod/hod_dashboard.html`**
   - Updated to safely access `rejected` field using `{% with %}` and `|default:False`

## Testing

After migration:
1. Dashboard should load without `OperationalError`
2. Pending submissions display correctly
3. Rejected items show with red background
4. Filtering by year/semester works for all sections
5. Approve/Reject buttons work correctly

## Notes

- No data loss - all new fields are nullable or have defaults
- Template is defensive - uses `|default:False` to handle missing field gracefully
- Filtering by year/semester was already correctly implemented
