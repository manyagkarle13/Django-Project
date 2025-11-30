from django.db import models



# Proxy models to surface HOD faculty and assignments under the `facultymodule` app
# These proxies reuse the tables from `hod` but have a different app_label so
# Django Admin will show a `facultymodule` section without duplicating data.
from hod.models import Faculty as HODFaculty


class Faculty(HODFaculty):
    class Meta:
        proxy = True
        app_label = 'facultymodule'
        verbose_name = 'Faculty'
        verbose_name_plural = 'Faculties'

