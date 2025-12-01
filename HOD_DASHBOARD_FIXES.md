# HOD Dashboard Fixes - Complete Solution

## A. Template Fix ✅

**Problem:** `VariableDoesNotExist` error when `s.created_by` is `None` (due to `on_delete=models.SET_NULL`).

**Why it occurs:** Django template tries to access `s.created_by.username` when `s.created_by` is `None`. The `default` filter only works if the attribute exists but is empty, not when the object itself is `None`.

**Fix Applied:**
```django
{# Before (line 246): #}
<td>{{ s.created_by.get_full_name|default:s.created_by.username }}</td>

{# After: #}
<td>{% if s.created_by %}{{ s.created_by.get_full_name|default:s.created_by.username }}{% else %}—{% endif %}</td>
```

This safely checks if `created_by` exists before accessing its attributes, showing "—" as a fallback.

---

## B. Revised View Queryset ✅

**Location:** `hod/views.py`, `dashboard()` function, lines 608-624

**Updated queryset:**
```python
# Fetch pending FacultySyllabusPDF submissions (not approved yet)
# Filter: exclude deleted courses, only show courses assigned to this branch (not college-wide),
# filter by year/semester if provided, exclude deleted submissions
pending_submissions = []
try:
    FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')
    CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
    
    # Base queryset: branch-specific, not approved, course exists and not deleted
    pending_qs = FacultySyllabusPDF.objects.filter(
        branch=branch,
        approved=False,
        course__isnull=False,  # Ensure course exists
        course__is_deleted=False,  # Exclude deleted courses
        course__branch=branch,  # Only courses assigned to this branch (exclude college-wide)
    )
    
    # Filter by year and semester if both are provided (required for proper filtering)
    if selected_year:
        pending_qs = pending_qs.filter(year=str(selected_year))
    if selected_semester:
        pending_qs = pending_qs.filter(semester=str(selected_semester))
    
    # Optimize queries with select_related
    pending_submissions = pending_qs.select_related('created_by', 'course', 'branch').order_by('-created_at')
except (LookupError, Exception) as e:
    logger.debug("FacultySyllabusPDF not found or error: %s", e)
    pending_submissions = []
```

**Key improvements:**
1. ✅ Excludes deleted courses: `course__is_deleted=False`
2. ✅ Excludes college-wide courses: `course__branch=branch` (only shows branch-specific courses)
3. ✅ Filters by department/branch: `branch=branch` and `course__branch=branch`
4. ✅ Filters by year/semester: Uses `selected_year` and `selected_semester` from query params
5. ✅ Optimizes queries: Uses `select_related()` to avoid N+1 queries
6. ✅ Handles missing course: `course__isnull=False` ensures course exists

---

## C. Data Cleanup Queries

Run these in Django shell (`python manage.py shell`) to find and fix orphaned records:

### 1. Find FacultySyllabusPDF with null created_by
```python
from hod.models import FacultySyllabusPDF

# Find submissions with null created_by
orphaned_pdfs = FacultySyllabusPDF.objects.filter(created_by__isnull=True)
print(f"Found {orphaned_pdfs.count()} PDFs with null created_by")

# Option 1: Delete them (if not needed)
# orphaned_pdfs.delete()

# Option 2: Mark as deleted (if you have is_deleted field)
# for pdf in orphaned_pdfs:
#     pdf.is_deleted = True
#     pdf.save()
```

### 2. Find FacultySyllabusPDF with deleted courses
```python
from hod.models import FacultySyllabusPDF
from academics.models import CollegeLevelCourse

# Find PDFs linked to deleted courses
pdfs_with_deleted_courses = FacultySyllabusPDF.objects.filter(
    course__is_deleted=True
)
print(f"Found {pdfs_with_deleted_courses.count()} PDFs with deleted courses")

# Option: Delete or mark as deleted
# pdfs_with_deleted_courses.delete()
```

### 3. Find FacultySyllabusPDF with null courses
```python
from hod.models import FacultySyllabusPDF

# Find PDFs with null course
pdfs_no_course = FacultySyllabusPDF.objects.filter(course__isnull=True)
print(f"Found {pdfs_no_course.count()} PDFs with null course")

# Option: Delete or update
# pdfs_no_course.delete()
```

### 4. Find FacultySyllabusPDF for wrong branch (college-wide courses)
```python
from hod.models import FacultySyllabusPDF

# Find PDFs where course.branch doesn't match PDF.branch
# (college-wide courses that shouldn't appear on HOD dashboard)
mismatched_branch = FacultySyllabusPDF.objects.filter(
    course__branch__isnull=True  # College-wide courses
).exclude(branch__isnull=True)  # But PDF has a branch assigned

print(f"Found {mismatched_branch.count()} PDFs with branch mismatch")

# Option: Update branch to None or delete
# for pdf in mismatched_branch:
#     pdf.branch = None
#     pdf.save()
```

### 5. Find Syllabus records with deleted courses
```python
from academics.models import Syllabus, CollegeLevelCourse

# Find syllabi with deleted courses
syllabi_deleted_courses = Syllabus.objects.filter(
    course__is_deleted=True
)
print(f"Found {syllabi_deleted_courses.count()} syllabi with deleted courses")

# Option: Mark as deleted
# for s in syllabi_deleted_courses:
#     s.is_deleted = True
#     s.save()
```

### 6. Comprehensive cleanup script
```python
from hod.models import FacultySyllabusPDF
from academics.models import Syllabus, CollegeLevelCourse

def cleanup_orphaned_records(dry_run=True):
    """
    Clean up orphaned records.
    Set dry_run=False to actually delete/update records.
    """
    print("=" * 60)
    print("CLEANUP REPORT")
    print("=" * 60)
    
    # 1. PDFs with null created_by
    pdfs_null_user = FacultySyllabusPDF.objects.filter(created_by__isnull=True)
    print(f"\n1. PDFs with null created_by: {pdfs_null_user.count()}")
    
    # 2. PDFs with deleted courses
    pdfs_deleted_course = FacultySyllabusPDF.objects.filter(course__is_deleted=True)
    print(f"2. PDFs with deleted courses: {pdfs_deleted_course.count()}")
    
    # 3. PDFs with null course
    pdfs_null_course = FacultySyllabusPDF.objects.filter(course__isnull=True)
    print(f"3. PDFs with null course: {pdfs_null_course.count()}")
    
    # 4. Syllabi with deleted courses
    syllabi_deleted = Syllabus.objects.filter(course__is_deleted=True, is_deleted=False)
    print(f"4. Syllabi with deleted courses (not marked deleted): {syllabi_deleted.count()}")
    
    if not dry_run:
        print("\n" + "=" * 60)
        print("EXECUTING CLEANUP...")
        print("=" * 60)
        
        # Delete orphaned PDFs
        total_deleted = pdfs_null_user.count() + pdfs_deleted_course.count() + pdfs_null_course.count()
        pdfs_null_user.delete()
        pdfs_deleted_course.delete()
        pdfs_null_course.delete()
        print(f"Deleted {total_deleted} orphaned PDFs")
        
        # Mark syllabi as deleted
        syllabi_deleted.update(is_deleted=True)
        print(f"Marked {syllabi_deleted.count()} syllabi as deleted")
        
        print("\nCleanup complete!")
    else:
        print("\n" + "=" * 60)
        print("DRY RUN - No changes made")
        print("Run with dry_run=False to execute cleanup")
        print("=" * 60)

# Run cleanup (dry run first!)
cleanup_orphaned_records(dry_run=True)

# Uncomment to actually execute:
# cleanup_orphaned_records(dry_run=False)
```

---

## D. Test Examples

### 1. Django Shell Test Commands

```python
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from academics.models import Branch, CollegeLevelCourse
from hod.models import FacultySyllabusPDF, HODAssignment
from hod.views import dashboard

User = get_user_model()

# Setup: Get a branch and HOD user
branch = Branch.objects.first()  # Replace with actual branch
hod_user = User.objects.filter(hod_assignment__branch=branch).first()

# Create a test request
factory = RequestFactory()
request = factory.get(f'/hod/dashboard/{branch.pk}/?year=2025&semester=3')
request.user = hod_user

# Test the view
response = dashboard(request, branch_pk=branch.pk)
context = response.context_data

# Assertions
print(f"Pending submissions count: {len(context.get('pending_submissions', []))}")

# Verify filtering
pending = context.get('pending_submissions', [])
for s in pending:
    assert s.branch == branch, "All submissions should be for this branch"
    assert s.approved == False, "All should be pending"
    assert s.course is not None, "Course should exist"
    assert s.course.is_deleted == False, "Course should not be deleted"
    assert s.course.branch == branch, "Course should be assigned to this branch"
    if s.created_by:
        assert s.created_by is not None, "created_by should exist if not None"

print("✅ All assertions passed!")
```

### 2. Unit Test Example

Create `hod/tests/test_dashboard_filtering.py`:

```python
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from academics.models import Branch, CollegeLevelCourse
from hod.models import FacultySyllabusPDF, HODAssignment
from hod.views import dashboard

User = get_user_model()

class HODDashboardFilteringTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.branch = Branch.objects.create(name="Test Branch", code="TB")
        self.hod_user = User.objects.create_user(
            username="hod_test",
            email="hod@test.com",
            password="testpass123"
        )
        self.hod_assignment = HODAssignment.objects.create(
            hod_user=self.hod_user,
            branch=self.branch
        )
        
        # Create a course assigned to this branch
        self.course = CollegeLevelCourse.objects.create(
            course_code="CS101",
            course_title="Test Course",
            branch=self.branch,
            is_deleted=False,
            semester=3
        )
        
        # Create a faculty user
        self.faculty_user = User.objects.create_user(
            username="faculty_test",
            email="faculty@test.com",
            password="testpass123"
        )
    
    def test_pending_submissions_excludes_deleted_courses(self):
        """Test that deleted courses are excluded"""
        # Create PDF with deleted course
        deleted_course = CollegeLevelCourse.objects.create(
            course_code="CS102",
            course_title="Deleted Course",
            branch=self.branch,
            is_deleted=True
        )
        FacultySyllabusPDF.objects.create(
            branch=self.branch,
            course=deleted_course,
            created_by=self.faculty_user,
            year="2025",
            semester="3",
            approved=False
        )
        
        request = self.factory.get(f'/hod/dashboard/{self.branch.pk}/?year=2025&semester=3')
        request.user = self.hod_user
        response = dashboard(request, branch_pk=self.branch.pk)
        
        pending = response.context_data.get('pending_submissions', [])
        # Should not include the deleted course
        self.assertEqual(len(pending), 0)
    
    def test_pending_submissions_excludes_college_wide_courses(self):
        """Test that college-wide courses (branch=None) are excluded"""
        # Create college-wide course
        college_course = CollegeLevelCourse.objects.create(
            course_code="CS103",
            course_title="College Course",
            branch=None,  # College-wide
            is_deleted=False
        )
        FacultySyllabusPDF.objects.create(
            branch=self.branch,
            course=college_course,
            created_by=self.faculty_user,
            year="2025",
            semester="3",
            approved=False
        )
        
        request = self.factory.get(f'/hod/dashboard/{self.branch.pk}/?year=2025&semester=3')
        request.user = self.hod_user
        response = dashboard(request, branch_pk=self.branch.pk)
        
        pending = response.context_data.get('pending_submissions', [])
        # Should not include college-wide course
        self.assertEqual(len(pending), 0)
    
    def test_pending_submissions_filters_by_year_semester(self):
        """Test that year and semester filtering works"""
        # Create PDF for correct year/semester
        pdf1 = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            course=self.course,
            created_by=self.faculty_user,
            year="2025",
            semester="3",
            approved=False
        )
        
        # Create PDF for different year
        pdf2 = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            course=self.course,
            created_by=self.faculty_user,
            year="2024",
            semester="3",
            approved=False
        )
        
        request = self.factory.get(f'/hod/dashboard/{self.branch.pk}/?year=2025&semester=3')
        request.user = self.hod_user
        response = dashboard(request, branch_pk=self.branch.pk)
        
        pending = response.context_data.get('pending_submissions', [])
        # Should only include pdf1
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].pk, pdf1.pk)
    
    def test_pending_submissions_handles_null_created_by(self):
        """Test that null created_by doesn't break the template"""
        # Create PDF with null created_by
        pdf = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            course=self.course,
            created_by=None,  # Null user
            year="2025",
            semester="3",
            approved=False
        )
        
        request = self.factory.get(f'/hod/dashboard/{self.branch.pk}/?year=2025&semester=3')
        request.user = self.hod_user
        response = dashboard(request, branch_pk=self.branch.pk)
        
        # Should not raise error
        self.assertEqual(response.status_code, 200)
        pending = response.context_data.get('pending_submissions', [])
        # PDF should still appear (if other filters pass)
        # Note: The template fix handles displaying null created_by safely
```

### 3. Manual Testing Checklist

Run these checks after applying fixes:

```python
# In Django shell
from academics.models import Branch, CollegeLevelCourse
from hod.models import FacultySyllabusPDF, HODAssignment
from django.contrib.auth import get_user_model

User = get_user_model()
branch = Branch.objects.first()  # Your test branch
hod_user = User.objects.filter(hod_assignment__branch=branch).first()

# 1. Check pending submissions count
pending = FacultySyllabusPDF.objects.filter(
    branch=branch,
    approved=False,
    course__isnull=False,
    course__is_deleted=False,
    course__branch=branch
)
print(f"Pending submissions for branch {branch.name}: {pending.count()}")

# 2. Verify no deleted courses
deleted_in_results = pending.filter(course__is_deleted=True).count()
assert deleted_in_results == 0, "No deleted courses should appear"
print("✅ No deleted courses in results")

# 3. Verify no college-wide courses
college_wide = pending.filter(course__branch__isnull=True).count()
assert college_wide == 0, "No college-wide courses should appear"
print("✅ No college-wide courses in results")

# 4. Verify all are for correct branch
wrong_branch = pending.exclude(course__branch=branch).count()
assert wrong_branch == 0, "All courses should be for this branch"
print("✅ All courses are for correct branch")

# 5. Check for null created_by (should be handled by template)
null_user = pending.filter(created_by__isnull=True).count()
print(f"⚠️  Found {null_user} submissions with null created_by (template should handle this)")
```

---

## Summary

### Changes Made:
1. ✅ **Template fix** (`hod/templates/hod/hod_dashboard.html` line 246): Added null check for `created_by`
2. ✅ **View queryset fix** (`hod/views.py` lines 608-624): Updated filtering to exclude deleted courses, college-wide courses, and properly filter by branch/year/semester

### Expected Results:
- ✅ No `VariableDoesNotExist` errors
- ✅ HOD only sees courses assigned to their branch
- ✅ Deleted courses don't appear
- ✅ College-wide courses don't appear on HOD dashboard
- ✅ Filtering by year/semester works correctly
- ✅ Template safely handles null `created_by` values

### Next Steps:
1. Run the cleanup queries to fix existing orphaned records
2. Run the test examples to validate the filtering
3. Test manually in the browser with different year/semester combinations

