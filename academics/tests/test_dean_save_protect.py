from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from hod.models import HODAssignment, CourseAllocation, Faculty
from academics.models import Branch, CollegeLevelCourse, Syllabus

User = get_user_model()


class DeanSaveProtectionTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code='CSE', name='Computer Science')
        self.hod_user = User.objects.create_user(email='hod3@example.com', password='pass')
        self.hod_user.role = 'hod'
        self.hod_user.save()
        self.hod_assignment = HODAssignment.objects.create(hod_user=self.hod_user, branch=self.branch)

        # Create course & existing syllabus (as if HOD/Faculty created it)
        self.course = CollegeLevelCourse.objects.create(
            department='All Branches',
            course_category='Main',
            course_code='CS301',
            course_title='Operating Systems',
        )
        self.syllabus = Syllabus.objects.create(course=self.course, objectives='Original objectives')

        # Dean user
        self.dean_user = User.objects.create_user(email='dean@example.com', password='pass')
        self.dean_user.role = 'dean'
        self.dean_user.save()

    def test_dean_save_does_not_overwrite_existing_syllabus(self):
        self.client.force_login(self.dean_user)
        url = reverse('academics:add_syllabus', args=[self.course.pk])
        resp = self.client.post(url, {
            'action': 'save_only',
            'objectives': 'Dean changed objectives',
        })
        self.assertEqual(resp.status_code, 302)
        self.syllabus.refresh_from_db()
        self.assertEqual(self.syllabus.objectives, 'Original objectives')
