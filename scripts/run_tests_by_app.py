import os
import sys
import importlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'syllabus_maker.settings')

import django
from django.conf import settings

django.setup()

apps = list(settings.INSTALLED_APPS)
# Filter local apps by checking for a package directory at project root
local_apps = []
for app in apps:
    # skip django and third-party apps roughly by ignoring those with 'django.' or 'rest_framework' or containing a dot
    if app.startswith('django.'):
        continue
    # convert dotted app to its last segment
    app_label = app.split('.')[-1]
    candidate_dir = os.path.join(ROOT, app_label)
    if os.path.isdir(candidate_dir):
        local_apps.append(app_label)

if not local_apps:
    print('No local apps found to test.')
    sys.exit(0)

print('Will run tests for these apps (in order):')
print('\n'.join(local_apps))

# Run manage.py test per app
for app in local_apps:
    print('\n--- Running tests for:', app, '---')
    rc = os.system(f'python manage.py test {app} -v 2')
    if rc != 0:
        print(f'App {app} had failures (exit {rc}). Continuing to next app.')

print('\nDone running per-app tests.')
