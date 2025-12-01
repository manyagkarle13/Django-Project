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
            semester=1
        )

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

        # create a faculty-approved submission (not dean course)
        self.fac_sub = FacultySyllabusPDF.objects.create(
            branch=self.branch,
            year='2025',
            semester='1',
            approved=True,
            course=None,
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
            'submissions': [str(self.fac_sub.pk)],
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/pdf', response['Content-Type'])
