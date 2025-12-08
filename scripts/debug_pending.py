import os
import django
from datetime import timedelta
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')
django.setup()
from django.contrib.auth import get_user_model
from academics.models import Branch, CollegeLevelCourse
from hod.models import FacultySyllabusPDF

User = get_user_model()

branch = Branch.objects.create(code='CSE2', name='Computer Science 2')
user = User.objects.create_user(username='f1', email='f1@test.com', password='pass', role='faculty')

course = CollegeLevelCourse.objects.create(course_code='LATEST001', course_title='Test Latest', course_category='OEC', branch=branch, semester=3, is_deleted=False)

old_dt = timezone.now() - timedelta(days=3)
new_dt = timezone.now() - timedelta(days=1)
old = FacultySyllabusPDF.objects.create(branch=branch, year='2025', semester='3', created_by=user, course=course, title='old', approved=False, rejected=False, created_at=old_dt)
new = FacultySyllabusPDF.objects.create(branch=branch, year='2025', semester='3', created_by=user, course=course, title='new', approved=False, rejected=False, created_at=new_dt)

print('old pk, created_at =', old.pk, old.created_at)
print('new pk, created_at =', new.pk, new.created_at)

pending_qs = FacultySyllabusPDF.objects.filter(branch=branch, approved=False, rejected=False, course__in=[course])
for p in pending_qs.order_by('-created_at'):
    print('order by -created_at:', p.pk, p.created_at)

all_pending = list(pending_qs.select_related('created_by', 'course', 'branch').order_by('-created_at'))
print('all_pending initial list pks:', [p.pk for p in all_pending])

# sort_key emulation

def sort_key(submission):
    try:
        sub_year = int(submission.year) if submission.year else 0
        sub_sem = int(submission.semester) if submission.semester else 0
    except Exception:
        sub_year = 0
        sub_sem = 0
    return (sub_year, sub_sem)

all_pending.sort(key=sort_key)
print('all_pending after sort key pks:', [p.pk for p in all_pending])

latest_per_course = {}
for submission in all_pending:
    cid = submission.course_id
    if not cid:
        continue
    existing = latest_per_course.get(cid)
    try:
        if not existing or (hasattr(submission, 'created_at') and hasattr(existing, 'created_at') and submission.created_at > existing.created_at):
            latest_per_course[cid] = submission
    except Exception:
        latest_per_course[cid] = submission

print('latest_per_course pks:', {k: v.pk for k, v in latest_per_course.items()})

print('done')
