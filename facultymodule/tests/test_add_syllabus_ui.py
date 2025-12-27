from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import Branch
from hod.models import HODAssignment, CourseAllocation, Faculty, FacultyAssignment

User = get_user_model()


class FacultyAddSyllabusViewTest(TestCase):
    def setUp(self):
        # create branch + hod + course allocation
        self.branch = Branch.objects.create(code='CSE', name='Computer Science')
        self.hod_user = User.objects.create_user(email='hod@example.com', password='pass')
        self.hod_user.role = 'hod'
        self.hod_user.save()
        self.hod_assignment = HODAssignment.objects.create(hod_user=self.hod_user, branch=self.branch)

        self.course_alloc = CourseAllocation.objects.create(
            hod_assignment=self.hod_assignment,
            course_code='CS101',
            course_title='Intro to CS',
            course_category='Main',
        )

        # create faculty user and profile
        self.fac_user = User.objects.create_user(email='fac@example.com', password='pass')
        self.fac_user.role = 'faculty'
        self.fac_user.save()
        self.fac_profile = Faculty.objects.create(user=self.fac_user)

        # assign faculty to course allocation
        self.fac_assign = FacultyAssignment.objects.create(faculty=self.fac_profile, course_allocation=self.course_alloc)

    def test_get_add_syllabus_renders_dean_template(self):
        self.client.force_login(self.fac_user)
        url = reverse('facultymodule:add_syllabus', args=[self.course_alloc.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # confirm that Dean template is used
        self.assertTemplateUsed(resp, 'academics/add_syllabus.html')
