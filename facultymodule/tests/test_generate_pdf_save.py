from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import Branch, CollegeLevelCourse
from hod.models import HODAssignment, CourseAllocation, Faculty, FacultyAssignment, FacultySyllabusPDF

User = get_user_model()


class GeneratePDFSaveOptionTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code='CSE', name='Computer Science')
        self.hod_user = User.objects.create_user(email='hod4@example.com', password='pass')
        self.hod_user.role = 'hod'
        self.hod_user.save()
        self.hod_assignment = HODAssignment.objects.create(hod_user=self.hod_user, branch=self.branch)

        self.course_alloc = CourseAllocation.objects.create(
            hod_assignment=self.hod_assignment,
            course_code='CS401',
            course_title='Compilers',
            course_category='Main',
        )

        self.fac_user = User.objects.create_user(email='fac4@example.com', password='pass')
        self.fac_user.role = 'faculty'
        self.fac_user.save()
        self.fac_profile = Faculty.objects.create(user=self.fac_user)
        self.fac_assign = FacultyAssignment.objects.create(faculty=self.fac_profile, course_allocation=self.course_alloc)

    def test_generate_pdf_without_save_creates_record_by_default(self):
        """Generate PDF without explicit save flag should create a FacultySyllabusPDF (faculty default)."""
        self.client.force_login(self.fac_user)
        url = reverse('facultymodule:add_syllabus', args=[self.course_alloc.pk])
        resp = self.client.post(url, {'action': 'generate_pdf'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(FacultySyllabusPDF.objects.filter(course__course_code=self.course_alloc.course_code).exists())

    def test_generate_pdf_with_save_creates_record(self):
        self.client.force_login(self.fac_user)
        url = reverse('facultymodule:add_syllabus', args=[self.course_alloc.pk])
        resp = self.client.post(url, {'action': 'generate_pdf', 'save_pdf': '1'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(FacultySyllabusPDF.objects.filter(course__course_code=self.course_alloc.course_code).exists())

    def test_view_pdf_link_appears_on_dashboard_after_save(self):
        """After saving a generated PDF, the faculty dashboard should show a 'View PDF' link."""
        self.client.force_login(self.fac_user)
        url = reverse('facultymodule:add_syllabus', args=[self.course_alloc.pk])
        # Generate and save the PDF
        resp = self.client.post(url, {'action': 'generate_pdf', 'save_pdf': '1'})
        self.assertEqual(resp.status_code, 200)
        # Now fetch the dashboard and assert the 'View PDF' link is present for the course
        dash = self.client.get(reverse('facultymodule:faculty_dashboard'))
        self.assertEqual(dash.status_code, 200)
        content = dash.content.decode('utf-8')
        # The dashboard should contain the link text and the course code in the same page
        self.assertIn('View PDF', content)
        self.assertIn(self.course_alloc.course_code, content)
        # Also assert that a link tag for 'View PDF' exists
        import re
        self.assertRegex(content, r'<a[^>]*>\s*View PDF\s*</a>')
