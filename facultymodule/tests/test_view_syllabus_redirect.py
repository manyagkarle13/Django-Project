from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import Branch
from hod.models import HODAssignment, CourseAllocation, Faculty, FacultyAssignment

User = get_user_model()


class ViewSyllabusRedirectTest(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code='CSE', name='Computer Science')
        self.hod_user = User.objects.create_user(email='hod2@example.com', password='pass')
        self.hod_user.role = 'hod'
        self.hod_user.save()
        self.hod_assignment = HODAssignment.objects.create(hod_user=self.hod_user, branch=self.branch)

        self.course_alloc = CourseAllocation.objects.create(
            hod_assignment=self.hod_assignment,
            course_code='CS201',
            course_title='Algorithms',
            course_category='Main',
        )

        self.fac_user = User.objects.create_user(email='fac2@example.com', password='pass')
        self.fac_user.role = 'faculty'
        self.fac_user.save()
        self.fac_profile = Faculty.objects.create(user=self.fac_user)
        self.fac_assign = FacultyAssignment.objects.create(faculty=self.fac_profile, course_allocation=self.course_alloc)

    def test_view_syllabus_redirects_to_add_syllabus(self):
        self.client.force_login(self.fac_user)
        url = reverse('facultymodule:view_syllabus', args=[self.course_alloc.pk])
        resp = self.client.get(url)
        self.assertIn(resp.status_code, (301, 302))
        expected = reverse('facultymodule:add_syllabus', args=[self.course_alloc.pk])
        # Location header may be full or relative; check it ends with expected path
        location = resp.get('Location', '')
        self.assertTrue(location.endswith(expected), f"Redirect location {location} does not end with {expected}")
