from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from django.apps import apps


class CombinedPDFTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(email='hod@example.com', password='pass')
        self.user.is_staff = True
        self.user.save()

        Branch = apps.get_model('academics', 'Branch')
        self.branch = Branch.objects.create(code='CSE', name='Computer Science')

        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        # create a dean course (branch is null => college-wide)
        self.dean_course = CollegeLevelCourse.objects.create(
            course_category='ESC',
            course_code='DEAN101',
            course_title='Dean Course',
            semester=1,
            admission_year='2025'
        )
        # attach a syllabus_pdf file directly to the course (represents Dean-provided file)
        self.dean_course.syllabus_pdf.save('dean_course.pdf', ContentFile(b'%PDF-1.4\n%EOF'))
        self.dean_course.save()

        FacultySyllabusPDF = apps.get_model('hod', 'FacultySyllabusPDF')

        # create a dean-approved submission (approved, linked to dean course)
        self.dean_sub = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='1',
            approved=True,
            course=self.dean_course,
        )
        # write a minimal PDF to the filefield
        self.dean_sub.pdf_file.save('dean.pdf', ContentFile(b'%PDF-1.4\n%EOF'))
        self.dean_sub.save()

        # create a faculty submission linked to a branch-specific course and save a PDF
        self.branch_course = CollegeLevelCourse.objects.create(
            course_category='CSE',
            course_code='CSE101',
            course_title='Branch Course',
            semester=1,
            admission_year='2025',
            branch=self.branch,
        )
        self.fac_sub = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='1',
            approved=True,
            course=self.branch_course,
        )
        self.fac_sub.pdf_file.save('fac.pdf', ContentFile(b'%PDF-1.4\n%EOF'))
        self.fac_sub.save()

        self.client = Client()
        self.client.force_login(self.user)

    def test_generate_combined_includes_dean_and_selected(self):
        url = reverse('hod:generate_combined_syllabus', args=[self.branch.pk])
        data = {
            'year': '2025',
            'semester': '1',
            # Choose the dean course file explicitly and the faculty submission
            'dean_course_ids': [str(self.dean_course.pk)],
            'latest_submissions': [str(self.fac_sub.pk)],
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/pdf', response['Content-Type'])
        # The generated response should be an attachment PDF
        self.assertIn('attachment; filename', response.get('Content-Disposition', ''))

    def test_create_combined_page_shows_selection_options(self):
        """Create combined syllabus page should render options to select dean course PDFs and latest faculty PDFs."""
        url = reverse('hod:create_combined_syllabus', args=[self.branch.pk]) + '?year=2025&semester=1'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        # Deprecated message should not be present
        self.assertNotIn('No approved PDFs found for the selected filters.', content)
        # Dean course checkbox label should appear
        self.assertIn('Dean course PDFs', content)
        # Latest faculty section should appear
        self.assertIn('Latest faculty-generated PDF per course', content)
        # The Dean course row should indicate Has File = Yes (we attached dean_course.syllabus_pdf earlier)
        self.assertIn('DEAN101', content)
        self.assertIn('Yes', content)

    def test_generate_combined_includes_generated_dean_syllabus(self):
        """If a dean course has no attached PDF but a textual Syllabus exists, it should be generated and included."""
        # Create a dean course without a file
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        Syllabus = apps.get_model('academics', 'Syllabus')
        dean_no_file = CollegeLevelCourse.objects.create(
            course_category='ESC',
            course_code='DEAN204',
            course_title='Dean Generated Syllabus',
            semester=1,
            admission_year='2025',
        )
        # Add a textual syllabus record
        Syllabus.objects.create(course=dean_no_file, objectives='Objectives here', outcomes='CO1')

        url = reverse('hod:generate_combined_syllabus', args=[self.branch.pk])
        data = {'year': '2025', 'semester': '1'}
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/pdf', resp['Content-Type'])
        self.assertIn('attachment; filename', resp.get('Content-Disposition', ''))

    def test_generate_combined_includes_generated_faculty_syllabus_when_no_saved_pdf(self):
        """If a faculty has a textual Syllabus but hasn't generated a saved FacultySyllabusPDF, HOD should generate it on-the-fly and include it."""
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')
        Syllabus = apps.get_model('academics', 'Syllabus')

        # Create a branch-specific course and textual syllabus (no FacultySyllabusPDF saved)
        branch_course = CollegeLevelCourse.objects.create(
            course_category='CSE',
            course_code='CSE202',
            course_title='Branch Course',
            semester=1,
            admission_year='2025',
            branch=self.branch,
        )
        Syllabus.objects.create(course=branch_course, objectives='Obj', outcomes='CO1')

        url = reverse('hod:generate_combined_syllabus', args=[self.branch.pk])
        data = {'year': '2025', 'semester': '1'}
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/pdf', resp['Content-Type'])
        self.assertIn('attachment; filename', resp.get('Content-Disposition', ''))
