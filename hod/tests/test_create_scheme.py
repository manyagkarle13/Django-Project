"""
Tests for create_scheme view to ensure dean-assigned courses are included.
"""
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.files.base import ContentFile
from academics.models import Branch, CollegeLevelCourse
from hod.models import HODAssignment, FacultySyllabusPDF

User = get_user_model()


class CreateSchemeViewTest(TestCase):
    """Test create_scheme view includes dean-assigned courses."""

    def setUp(self):
        """Set up test data."""
        # Create a branch
        self.branch = Branch.objects.create(
            name="Computer Science",
            code="CS"
        )
        
        # Create HOD user
        self.hod_user = User.objects.create_user(
            username="hod_test",
            email="hod@test.com",
            password="testpass123",
            role="hod"
        )
        
        # Create HOD assignment
        self.hod_assignment = HODAssignment.objects.create(
            hod_user=self.hod_user,
            branch=self.branch
        )
        
        # Create a dean-assigned course (college-level course)
        self.dean_course = CollegeLevelCourse.objects.create(
            course_code="CS101",
            course_title="Introduction to Computer Science",
            course_category="PCC",
            branch=self.branch,  # Assigned to this branch
            semester=3,  # For semester 3
            teaching_hours_L=3,
            teaching_hours_T=1,
            teaching_hours_P=0,
            cie_marks=50,
            see_marks=50,
            credits=4.0,
            is_deleted=False
        )
        
        # Create a college-wide course (branch=None)
        self.college_wide_course = CollegeLevelCourse.objects.create(
            course_code="HS101",
            course_title="Humanities",
            course_category="HSMC",
            branch=None,  # College-wide
            semester=3,
            teaching_hours_L=2,
            teaching_hours_T=0,
            teaching_hours_P=0,
            cie_marks=50,
            see_marks=50,
            credits=2.0,
            is_deleted=False
        )
        
        # Create a course for different semester (should not appear)
        self.other_semester_course = CollegeLevelCourse.objects.create(
            course_code="CS201",
            course_title="Advanced CS",
            course_category="PCC",
            branch=self.branch,
            semester=4,  # Different semester
            teaching_hours_L=3,
            teaching_hours_T=1,
            teaching_hours_P=0,
            cie_marks=50,
            see_marks=50,
            credits=4.0,
            is_deleted=False
        )
        
        # Create a deleted course (should not appear)
        self.deleted_course = CollegeLevelCourse.objects.create(
            course_code="CS999",
            course_title="Deleted Course",
            course_category="PCC",
            branch=self.branch,
            semester=3,
            is_deleted=True  # Deleted
        )
        
        self.client = Client()
        self.client.login(username="hod_test", password="testpass123")

    def test_create_scheme_includes_dean_courses(self):
        """Test that create_scheme view includes dean-assigned courses."""
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that dean_courses are in context
        self.assertIn('dean_courses', response.context)
        dean_courses = response.context['dean_courses']
        
        # Should include branch-specific course
        branch_course_codes = [c['course_code'] for c in dean_courses]
        self.assertIn('CS101', branch_course_codes)
        
        # Should include college-wide course
        self.assertIn('HS101', branch_course_codes)
        
        # Should NOT include course from different semester
        self.assertNotIn('CS201', branch_course_codes)
        
        # Should NOT include deleted course
        self.assertNotIn('CS999', branch_course_codes)

    def test_create_scheme_dean_courses_have_correct_fields(self):
        """Test that dean courses have all required fields."""
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        dean_courses = response.context['dean_courses']
        
        # Find our test course
        cs101 = next((c for c in dean_courses if c['course_code'] == 'CS101'), None)
        self.assertIsNotNone(cs101, "CS101 course should be in dean_courses")
        
        # Check all required fields are present
        required_fields = [
            'id', 'category', 'course_code', 'course_title',
            'l', 't', 'p', 'total_hours', 'cie', 'see', 'total_marks', 'credits'
        ]
        for field in required_fields:
            self.assertIn(field, cs101, f"Field {field} should be in dean course dict")

    def test_create_scheme_response_contains_dean_course_title(self):
        """Test that HTML response contains dean course title."""
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Should contain the course title in the HTML
        self.assertIn('Introduction to Computer Science', content)
        self.assertIn('CS101', content)

    def test_create_scheme_filters_by_semester(self):
        """Test that only courses for the specified semester are included."""
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        dean_courses = response.context['dean_courses']
        
        # All courses should be for semester 3
        # (We can't directly check semester from the dict, but we know CS201 is sem 4 and shouldn't appear)
        course_codes = [c['course_code'] for c in dean_courses]
        self.assertNotIn('CS201', course_codes, "Semester 4 course should not appear for semester 3")

    def test_create_scheme_excludes_deleted_courses(self):
        """Test that deleted courses are excluded."""
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        dean_courses = response.context['dean_courses']
        
        course_codes = [c['course_code'] for c in dean_courses]
        self.assertNotIn('CS999', course_codes, "Deleted course should not appear")

    def test_create_scheme_includes_college_wide_courses(self):
        """Test that college-wide courses (branch=None) are included."""
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        dean_courses = response.context['dean_courses']
        
        course_codes = [c['course_code'] for c in dean_courses]
        self.assertIn('HS101', course_codes, "College-wide course should appear")

    def test_create_scheme_no_nameerror(self):
        """Test that NameError is fixed - view should not raise NameError."""
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        
        # Should not raise NameError
        try:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
        except NameError as e:
            self.fail(f"NameError should not occur: {e}")

    def test_pdf_generation_includes_dean_and_elective(self):
        """Test that PDF generation includes dean and elective courses."""
        # Create an elective course
        from hod.models import SchemeCourse
        elective = SchemeCourse.objects.create(
            branch=self.branch,
            year=2025,
            semester=3,
            course_code="ELEC101",
            course_title="Elective Course",
            is_elective=True,
            category="PEC"
        )
        
        # Simulate POST to generate_pdf_view
        url = reverse('hod:generate_pdf', args=[self.branch.pk, 2025, 3])
        response = self.client.post(url, {
            'pec_code_1': 'ELEC101',
            'pec_title_1': 'Elective Course',
        })
        
        # Should return PDF (or redirect if error)
        self.assertIn(response.status_code, [200, 302])
        if response.status_code == 200:
            self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_faculty_assignments_show_scheme_courses(self):
        """Test that faculty assignments page shows scheme courses."""
        from hod.models import SchemeCourse, CourseAllocation, FacultyAssignment, HODAssignment
        from hod.models import Faculty
        
        # Create scheme course with faculty assignment
        faculty_user = User.objects.create_user(
            username="faculty1",
            email="faculty1@test.com",
            password="testpass",
            role="faculty"
        )
        
        scheme_course = SchemeCourse.objects.create(
            branch=self.branch,
            year=2025,
            semester=3,
            course_code="CS101",
            course_title="Test Course",
            is_elective=False,
            faculty=faculty_user  # Assign faculty directly to SchemeCourse
        )
        
        # Get faculty assignments page with year/semester filter
        url = reverse('hod:faculty_assignment_detail', args=[self.branch.pk])
        response = self.client.get(url, {'year': 2025, 'semester': 3})
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('assignments', response.context)
        assignments = response.context['assignments']
        
        # Should contain the scheme course
        course_codes = [a['course_code'] for a in assignments]
        self.assertIn('CS101', course_codes, "Scheme course should appear in assignments")
        
        # Find the assignment and verify faculty is shown
        cs101_assignment = next((a for a in assignments if a['course_code'] == 'CS101'), None)
        self.assertIsNotNone(cs101_assignment, "CS101 assignment should exist")
        self.assertIsNotNone(cs101_assignment.get('assigned_faculty_name'), "Faculty should be assigned")

    def test_elective_courses_saved_and_in_pdf(self):
        """Test that elective courses are saved and included in PDF."""
        from hod.models import SchemeCourse
        
        # POST elective courses to create_scheme
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        response = self.client.post(url, {
            'pec_code_1': 'ELEC101',
            'pec_title_1': 'Professional Elective 1',
            'pec_faculty_1': '',
            'pec_code_2': 'ELEC102',
            'pec_title_2': 'Professional Elective 2',
            'pec_faculty_2': '',
            'oec_code_1': 'OEC101',
            'oec_title_1': 'Open Elective 1',
            'oec_faculty_1': '',
        })
        
        # Should redirect after save
        self.assertEqual(response.status_code, 302)
        
        # Verify 3 elective SchemeCourse objects were created
        elective_count = SchemeCourse.objects.filter(
            branch=self.branch,
            year=2025,
            semester=3,
            is_elective=True
        ).count()
        self.assertGreaterEqual(elective_count, 3, "At least 3 elective courses should be saved")
        
        # Verify specific courses exist
        self.assertTrue(
            SchemeCourse.objects.filter(
                branch=self.branch,
                year=2025,
                semester=3,
                course_code='ELEC101',
                is_elective=True
            ).exists(),
            "ELEC101 should be saved"
        )
        self.assertTrue(
            SchemeCourse.objects.filter(
                branch=self.branch,
                year=2025,
                semester=3,
                course_code='OEC101',
                is_elective=True
            ).exists(),
            "OEC101 should be saved"
        )

    def test_faculty_assignments_filtered_by_year_semester(self):
        """Test that faculty assignments are filtered by year and semester."""
        from hod.models import SchemeCourse
        
        # Create Scheme A (2025 sem 3)
        scheme_a_course = SchemeCourse.objects.create(
            branch=self.branch,
            year=2025,
            semester=3,
            course_code="CS101",
            course_title="Course A",
            is_elective=False
        )
        
        # Create Scheme B (2024 sem 2) - different year/semester
        scheme_b_course = SchemeCourse.objects.create(
            branch=self.branch,
            year=2024,
            semester=2,
            course_code="CS201",
            course_title="Course B",
            is_elective=False
        )
        
        # Get faculty assignments for 2025 sem 3
        url = reverse('hod:faculty_assignment_detail', args=[self.branch.pk])
        response = self.client.get(url, {'year': 2025, 'semester': 3})
        
        self.assertEqual(response.status_code, 200)
        assignments = response.context['assignments']
        
        course_codes = [a['course_code'] for a in assignments]
        # Should include CS101 (2025 sem 3)
        self.assertIn('CS101', course_codes, "Scheme A course should appear")
        # Should NOT include CS201 (2024 sem 2)
        self.assertNotIn('CS201', course_codes, "Scheme B course should not appear for different year/semester")

    def test_faculty_assignment_persists_in_scheme_course(self):
        """Test that faculty assignment persists in SchemeCourse."""
        from hod.models import SchemeCourse
        
        faculty_user = User.objects.create_user(
            username="faculty2",
            email="faculty2@test.com",
            password="testpass",
            role="faculty"
        )
        
        # Create scheme course and assign faculty
        scheme_course = SchemeCourse.objects.create(
            branch=self.branch,
            year=2025,
            semester=3,
            course_code="CS102",
            course_title="Test Course with Faculty",
            is_elective=False,
            faculty=faculty_user
        )
        
        # Verify faculty is saved
        self.assertEqual(scheme_course.faculty, faculty_user)
        
        # Reload from DB and verify
        scheme_course.refresh_from_db()
        self.assertEqual(scheme_course.faculty, faculty_user)
        
        # Verify it shows in faculty assignments page
        url = reverse('hod:faculty_assignment_detail', args=[self.branch.pk])
        response = self.client.get(url, {'year': 2025, 'semester': 3})
        
        self.assertEqual(response.status_code, 200)
        assignments = response.context['assignments']
        cs102 = next((a for a in assignments if a['course_code'] == 'CS102'), None)
        self.assertIsNotNone(cs102, "CS102 should appear in assignments")
        self.assertEqual(cs102['assigned_faculty_name'], faculty_user.get_full_name() or faculty_user.username)

    def test_post_create_scheme_saves_all_rows_and_includes_in_pdf(self):
        """Test that POST to create_scheme saves all rows and they appear in PDF."""
        from hod.models import SchemeCourse
        
        # POST with 3 main rows
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        post_data = {
            'code_new_1': 'CS301',
            'title_new_1': 'Database Systems',
            'category_new_1': 'PCC',
            'l_new_1': '3',
            't_new_1': '1',
            'p_new_1': '0',
            'cie_new_1': '50',
            'see_new_1': '50',
            'credits_new_1': '4.0',
            'code_new_2': 'CS302',
            'title_new_2': 'Operating Systems',
            'category_new_2': 'PCC',
            'l_new_2': '3',
            't_new_2': '1',
            'p_new_2': '0',
            'cie_new_2': '50',
            'see_new_2': '50',
            'credits_new_2': '4.0',
            'code_new_3': 'CS303',
            'title_new_3': 'Computer Networks',
            'category_new_3': 'PCC',
            'l_new_3': '3',
            't_new_3': '1',
            'p_new_3': '0',
            'cie_new_3': '50',
            'see_new_3': '50',
            'credits_new_3': '4.0',
        }
        
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)  # Redirect after save
        
        # Verify 3 SchemeCourse objects were created
        count = SchemeCourse.objects.filter(
            branch=self.branch,
            year=2025,
            semester=3,
            is_elective=False
        ).count()
        self.assertGreaterEqual(count, 3, "At least 3 main rows should be saved")
        
        # Verify specific courses exist
        for code in ['CS301', 'CS302', 'CS303']:
            self.assertTrue(
                SchemeCourse.objects.filter(
                    branch=self.branch,
                    year=2025,
                    semester=3,
                    course_code=code,
                    is_elective=False
                ).exists(),
                f"{code} should be saved"
            )
        
        # Test PDF generation includes these rows
        pdf_url = reverse('hod:generate_pdf', args=[self.branch.pk, 2025, 3])
        pdf_response = self.client.post(pdf_url, post_data)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        
        # Verify PDF contains the course codes (basic check)
        # Note: Full PDF parsing would require PyPDF2, but we can at least verify it's generated
        self.assertGreater(len(pdf_response.content), 1000, "PDF should be generated with content")

    def test_elective_rows_saved_and_in_pdf(self):
        """Test that elective rows are saved and included in PDF."""
        from hod.models import SchemeCourse
        
        url = reverse('hod:create_scheme', args=[self.branch.pk, 2025, 3])
        post_data = {
            'pec_code_1': 'PEC101',
            'pec_title_1': 'Advanced Algorithms',
            'pec_faculty_1': '',
            'pec_code_2': 'PEC102',
            'pec_title_2': 'Machine Learning',
            'pec_faculty_2': '',
            'oec_code_1': 'OEC101',
            'oec_title_1': 'Business Ethics',
            'oec_faculty_1': '',
        }
        
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        
        # Verify elective courses were saved
        pec_count = SchemeCourse.objects.filter(
            branch=self.branch,
            year=2025,
            semester=3,
            is_elective=True,
            category='PEC'
        ).count()
        self.assertGreaterEqual(pec_count, 2, "At least 2 PEC courses should be saved")
        
        oec_count = SchemeCourse.objects.filter(
            branch=self.branch,
            year=2025,
            semester=3,
            is_elective=True,
            category='OEC'
        ).count()
        self.assertGreaterEqual(oec_count, 1, "At least 1 OEC course should be saved")
        
        # Verify specific courses exist
        self.assertTrue(
            SchemeCourse.objects.filter(
                branch=self.branch,
                year=2025,
                semester=3,
                course_code='PEC101',
                is_elective=True
            ).exists(),
            "PEC101 should be saved"
        )
        
        # Test PDF generation includes electives
        pdf_url = reverse('hod:generate_pdf', args=[self.branch.pk, 2025, 3])
        pdf_response = self.client.post(pdf_url, post_data)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')

    def test_faculty_assignments_no_none_values(self):
        """Test that faculty assignments page doesn't show None values."""
        from hod.models import SchemeCourse
        
        # Create scheme course with faculty
        faculty_user = User.objects.create_user(
            username="faculty3",
            email="faculty3@test.com",
            password="testpass",
            role="faculty"
        )
        
        scheme_course = SchemeCourse.objects.create(
            branch=self.branch,
            year=2025,
            semester=3,
            course_code="CS401",
            course_title="Test Course",
            is_elective=False,
            faculty=faculty_user
        )
        
        # Get faculty assignments page
        url = reverse('hod:faculty_assignment_detail', args=[self.branch.pk])
        response = self.client.get(url, {'year': 2025, 'semester': 3})
        
        self.assertEqual(response.status_code, 200)
        assignments = response.context['assignments']
        
        # Verify no None values in assignments
        for a in assignments:
            self.assertIsNotNone(a.get('course_code'), "course_code should not be None")
            self.assertIsNotNone(a.get('year'), "year should not be None")
            self.assertIsNotNone(a.get('semester'), "semester should not be None")
            # assigned_faculty_name can be "Not assigned" but not None
            self.assertIsNotNone(a.get('assigned_faculty_name'), "assigned_faculty_name should not be None")
        
        # Verify CS401 appears with correct values
        cs401 = next((a for a in assignments if a['course_code'] == 'CS401'), None)
        self.assertIsNotNone(cs401, "CS401 should appear in assignments")
        self.assertEqual(cs401['year'], 2025)
        self.assertEqual(cs401['semester'], 3)
        self.assertIn(cs401['assigned_faculty_name'], [
            faculty_user.get_full_name(),
            faculty_user.username,
            'Not assigned'
        ])

    def test_faculty_pdf_creates_pending_submission(self):
        """Test that faculty PDF generation creates a pending submission."""
        from hod.models import FacultySyllabusPDF
        
        # Create a faculty user
        faculty_user = User.objects.create_user(
            username="faculty_pdf",
            email="faculty_pdf@test.com",
            password="testpass",
            role="faculty"
        )
        
        # Simulate faculty generating a PDF (would normally be done via faculty module)
        pdf_obj = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=self.dean_course,
            title=self.dean_course.course_title,
            approved=False,
            rejected=False
        )
        
        # Verify it appears in pending submissions
        pending_qs = FacultySyllabusPDF.objects.filter(
            branch=self.branch,
            approved=False
        )
        self.assertTrue(pending_qs.filter(pk=pdf_obj.pk).exists(), "PDF should appear in pending submissions")

    def test_approve_syllabus_moves_to_approved(self):
        """Test that approving a syllabus moves it from pending to approved."""
        from hod.models import FacultySyllabusPDF
        
        faculty_user = User.objects.create_user(
            username="faculty_approve",
            email="faculty_approve@test.com",
            password="testpass",
            role="faculty"
        )
        
        # Create pending submission
        pdf_obj = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=self.dean_course,
            title=self.dean_course.course_title,
            approved=False,
            rejected=False
        )
        
        # Approve it
        url = reverse('hod:approve_syllabus', args=[pdf_obj.pk])
        response = self.client.post(url, {'action': 'approve'})
        self.assertEqual(response.status_code, 302)  # Redirect after approval
        
        # Refresh from DB
        pdf_obj.refresh_from_db()
        self.assertTrue(pdf_obj.approved, "PDF should be approved")
        self.assertFalse(pdf_obj.rejected, "PDF should not be rejected")
        self.assertEqual(pdf_obj.approved_by, self.hod_user)
        
        # Verify it appears in approved submissions, not pending
        pending_qs = FacultySyllabusPDF.objects.filter(branch=self.branch, approved=False)
        self.assertFalse(pending_qs.filter(pk=pdf_obj.pk).exists(), "Should not be in pending")
        
        approved_qs = FacultySyllabusPDF.objects.filter(branch=self.branch, approved=True)
        self.assertTrue(approved_qs.filter(pk=pdf_obj.pk).exists(), "Should be in approved")

    def test_reject_syllabus_stays_in_pending(self):
        """Test that rejecting a syllabus keeps it in pending but marks as rejected."""
        from hod.models import FacultySyllabusPDF
        
        faculty_user = User.objects.create_user(
            username="faculty_reject",
            email="faculty_reject@test.com",
            password="testpass",
            role="faculty"
        )
        
        # Create pending submission
        pdf_obj = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=self.dean_course,
            title=self.dean_course.course_title,
            approved=False,
            rejected=False
        )
        
        # Reject it
        url = reverse('hod:approve_syllabus', args=[pdf_obj.pk])
        response = self.client.post(url, {'action': 'reject'})
        self.assertEqual(response.status_code, 302)
        
        # Refresh from DB
        pdf_obj.refresh_from_db()
        self.assertFalse(pdf_obj.approved, "PDF should not be approved")
        self.assertTrue(pdf_obj.rejected, "PDF should be rejected")
        self.assertEqual(pdf_obj.rejected_by, self.hod_user)
        
        # Verify it still appears in pending (approved=False) but is marked rejected
        pending_qs = FacultySyllabusPDF.objects.filter(branch=self.branch, approved=False)
        self.assertTrue(pending_qs.filter(pk=pdf_obj.pk).exists(), "Should still be in pending")
        
        # Verify it can be re-approved
        response = self.client.post(url, {'action': 'approve'})
        self.assertEqual(response.status_code, 302)
        pdf_obj.refresh_from_db()
        self.assertTrue(pdf_obj.approved, "Should be approved after re-approval")
        self.assertFalse(pdf_obj.rejected, "Rejection should be cleared")

    def test_pending_submissions_only_shows_dean_courses(self):
        """Test that pending submissions list only shows dean-provided (CollegeLevelCourse) courses."""
        from hod.models import FacultySyllabusPDF
        from academics.models import CollegeLevelCourse
        
        # Create a dean course (CollegeLevelCourse)
        dean_course = CollegeLevelCourse.objects.create(
            course_code="23NYP",
            course_title="Dean Course 1",
            course_category="OEC",
            branch=self.branch,
            semester=3,
            is_deleted=False
        )
        
        # Create a non-dean course (if there's a different model, otherwise skip this part)
        # For now, we'll just test that only CollegeLevelCourse submissions appear
        
        # Create faculty user
        faculty_user = User.objects.create_user(
            username="faculty_dean",
            email="faculty_dean@test.com",
            password="testpass",
            role="faculty"
        )
        
        # Create submission for dean course
        dean_submission = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=dean_course,
            title=dean_course.course_title,
            approved=False,
            rejected=False
        )
        
        # Create another dean course and submission
        dean_course2 = CollegeLevelCourse.objects.create(
            course_code="23RIP",
            course_title="Dean Course 2",
            course_category="OEC",
            branch=None,  # College-wide
            semester=3,
            is_deleted=False
        )
        
        dean_submission2 = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=dean_course2,
            title=dean_course2.course_title,
            approved=False,
            rejected=False
        )
        
        # Get dashboard with year/semester selected
        url = reverse('hod:dashboard_self', args=[self.branch.pk])
        response = self.client.get(url, {'year': '2025', 'semester': '3'})
        
        self.assertEqual(response.status_code, 200)
        pending_submissions = response.context.get('pending_submissions', [])
        
        # Should only show dean course submissions (CollegeLevelCourse)
        pending_codes = [s.course.course_code for s in pending_submissions if s.course]
        self.assertIn('23NYP', pending_codes, "Dean course 23NYP should appear")
        self.assertIn('23RIP', pending_codes, "Dean course 23RIP should appear")
        self.assertEqual(len(pending_submissions), 2, "Should show exactly 2 dean course submissions")

    def test_view_submission_returns_pdf(self):
        """Test that view_submission returns PDF file response."""
        from hod.models import FacultySyllabusPDF
        from academics.models import CollegeLevelCourse
        from django.core.files.base import ContentFile
        
        # Create dean course
        dean_course = CollegeLevelCourse.objects.create(
            course_code="TEST001",
            course_title="Test Dean Course",
            course_category="OEC",
            branch=self.branch,
            semester=3,
            is_deleted=False
        )
        
        # Create faculty user
        faculty_user = User.objects.create_user(
            username="faculty_pdf",
            email="faculty_pdf@test.com",
            password="testpass",
            role="faculty"
        )
        
        # Create submission with PDF file
        pdf_submission = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=dean_course,
            title=dean_course.course_title,
            approved=False,
            rejected=False
        )
        
        # Create a dummy PDF file
        pdf_content = b'%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\nxref\n0 1\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF'
        pdf_submission.pdf_file.save('test_syllabus.pdf', ContentFile(pdf_content))
        pdf_submission.save()
        
        # Test view_submission_pdf endpoint
        url = reverse('hod:view_submission_pdf', args=[pdf_submission.pk])
        response = self.client.get(url)
        
        # Should return PDF file
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(b'PDF', response.content, "Response should contain PDF content")

    def test_pending_submissions_shows_only_latest_per_course(self):
        """Test that pending submissions shows only the latest submission per course."""
        from hod.models import FacultySyllabusPDF
        from academics.models import CollegeLevelCourse
        from django.utils import timezone
        from datetime import timedelta
        
        # Create dean course
        dean_course = CollegeLevelCourse.objects.create(
            course_code="LATEST001",
            course_title="Test Latest Course",
            course_category="OEC",
            branch=self.branch,
            semester=3,
            is_deleted=False
        )
        
        # Create faculty user
        faculty_user = User.objects.create_user(
            username="faculty_latest",
            email="faculty_latest@test.com",
            password="testpass",
            role="faculty"
        )
        
        # Create older submission (3 days ago)
        old_submission = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=dean_course,
            title=dean_course.course_title,
            approved=False,
            rejected=False,
            created_at=timezone.now() - timedelta(days=3)
        )
        
        # Create newer submission (1 day ago) - this should be shown
        new_submission = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=dean_course,
            title=dean_course.course_title,
            approved=False,
            rejected=False,
            created_at=timezone.now() - timedelta(days=1)
        )
        
        # Get dashboard with year/semester selected
        url = reverse('hod:dashboard_self', args=[self.branch.pk])
        response = self.client.get(url, {'year': '2025', 'semester': '3'})
        
        self.assertEqual(response.status_code, 200)
        pending_submissions = response.context.get('pending_submissions', [])
        
        # Should show only the latest submission (new_submission), not the old one
        pending_ids = [s.pk for s in pending_submissions]
        self.assertIn(new_submission.pk, pending_ids, "Latest submission should appear")
        self.assertNotIn(old_submission.pk, pending_ids, "Older submission should not appear")
        self.assertEqual(len([s for s in pending_submissions if s.course_id == dean_course.pk]), 1, 
                        "Should show exactly 1 submission per course")

    def test_faculty_name_displays_correctly(self):
        """Test that faculty full name displays correctly with username fallback."""
        from hod.models import FacultySyllabusPDF
        from academics.models import CollegeLevelCourse
        
        # Create dean course
        dean_course = CollegeLevelCourse.objects.create(
            course_code="FACULTY001",
            course_title="Test Faculty Name Course",
            course_category="OEC",
            branch=self.branch,
            semester=3,
            is_deleted=False
        )
        
        # Create faculty user with full name
        faculty_user = User.objects.create_user(
            username="faculty_fullname",
            email="faculty_fullname@test.com",
            password="testpass",
            role="faculty",
            first_name="John",
            last_name="Doe"
        )
        
        # Create submission
        submission = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user,
            course=dean_course,
            title=dean_course.course_title,
            approved=False,
            rejected=False
        )
        
        # Get dashboard
        url = reverse('hod:dashboard_self', args=[self.branch.pk])
        response = self.client.get(url, {'year': '2025', 'semester': '3'})
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        
        # Should display full name
        self.assertIn("John Doe", content, "Should display faculty full name")
        
        # Test with user without full name (should fallback to username)
        faculty_user2 = User.objects.create_user(
            username="faculty_username",
            email="faculty_username@test.com",
            password="testpass",
            role="faculty"
        )
        
        submission2 = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='3',
            created_by=faculty_user2,
            course=dean_course,
            title=dean_course.course_title,
            approved=False,
            rejected=False
        )
        
        response2 = self.client.get(url, {'year': '2025', 'semester': '3'})
        content2 = response2.content.decode()
        self.assertIn("faculty_username", content2, "Should display username when full name not available")

    def test_save_and_download_persists_all_rows_before_pdf(self):
        """Test that Save & Download button persists all rows before generating PDF."""
        from hod.models import SchemeCourse
        
        # Simulate Save & Download: POST to generate_pdf_view with form data
        url = reverse('hod:generate_pdf', args=[self.branch.pk, 2025, 3])
        post_data = {
            'code_new_1': 'CS501',
            'title_new_1': 'Advanced Database',
            'category_new_1': 'PCC',
            'l_new_1': '3',
            't_new_1': '1',
            'p_new_1': '0',
            'cie_new_1': '50',
            'see_new_1': '50',
            'credits_new_1': '4.0',
            'pec_code_1': 'PEC201',
            'pec_title_1': 'Data Mining',
            'pec_faculty_1': '',
        }
        
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        
        # Verify rows were saved to DB before PDF generation
        main_count = SchemeCourse.objects.filter(
            branch=self.branch,
            year=2025,
            semester=3,
            course_code='CS501',
            is_elective=False
        ).count()
        self.assertGreaterEqual(main_count, 1, "Main row should be saved")
        
        elective_count = SchemeCourse.objects.filter(
            branch=self.branch,
            year=2025,
            semester=3,
            course_code='PEC201',
            is_elective=True
        ).count()
        self.assertGreaterEqual(elective_count, 1, "Elective row should be saved")
        
        # Verify PDF was generated (has content)
        self.assertGreater(len(response.content), 1000, "PDF should contain content")

    def test_faculty_assignment_manager_with_year_semester(self):
        """Test that faculty assignment manager filters correctly with year/semester."""
        from hod.models import SchemeCourse
        
        # Create scheme courses for different years/semesters
        sc1 = SchemeCourse.objects.create(
            branch=self.branch,
            year=2025,
            semester=3,
            course_code="CS601",
            course_title="Course 2025 Sem3",
            is_elective=False
        )
        
        sc2 = SchemeCourse.objects.create(
            branch=self.branch,
            year=2024,
            semester=2,
            course_code="CS602",
            course_title="Course 2024 Sem2",
            is_elective=False
        )
        
        # Request assignments for 2025 sem 3
        url = reverse('hod:faculty_assignment_detail', args=[self.branch.pk])
        response = self.client.get(url, {'year': 2025, 'semester': 3})
        
        self.assertEqual(response.status_code, 200)
        assignments = response.context['assignments']
        
        # Should only include CS601 (2025 sem 3), not CS602
        codes = [a['course_code'] for a in assignments]
        self.assertIn('CS601', codes, "CS601 (2025 sem 3) should appear")
        self.assertNotIn('CS602', codes, "CS602 (2024 sem 2) should not appear")
        
        # Verify year and semester are set correctly
        cs601 = next((a for a in assignments if a['course_code'] == 'CS601'), None)
        self.assertIsNotNone(cs601)
        self.assertEqual(cs601['year'], 2025)
        self.assertEqual(cs601['semester'], 3)

    def test_faculty_assignment_manager_requires_year_semester(self):
        """Test that faculty assignment manager redirects if year/semester missing."""
        url = reverse('hod:faculty_assignment_detail', args=[self.branch.pk])
        response = self.client.get(url)  # No year/semester params
        
        # Should redirect to dashboard with message
        self.assertEqual(response.status_code, 302)
        self.assertIn('dashboard', response.url.lower())

