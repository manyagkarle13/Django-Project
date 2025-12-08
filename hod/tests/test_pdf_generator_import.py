from django.test import TestCase
from django.apps import apps
import importlib
import io


class PDFGeneratorImportTest(TestCase):
    def test_academics_generator_callable(self):
        """Ensure a syllabus PDF generator exists and returns a buffer-like object."""
        acad_views = importlib.import_module('academics.views')
        self.assertTrue(hasattr(acad_views, 'generate_syllabus_pdf_buffer'),
                        'academics.views should define generate_syllabus_pdf_buffer')
        gen = acad_views.generate_syllabus_pdf_buffer

        # Obtain or create a minimal Syllabus instance for the generator to consume.
        Syllabus = apps.get_model('academics', 'Syllabus')
        CollegeLevelCourse = apps.get_model('academics', 'CollegeLevelCourse')

        s = Syllabus.objects.first()
        if s is None:
            course = CollegeLevelCourse.objects.create(course_code='TEST101', course_title='Test Course')
            s = Syllabus.objects.create(course=course)

        buf = gen(s)
        # Accept bytes, bytearray or a BytesIO-like object
        self.assertTrue(isinstance(buf, (bytes, bytearray)) or hasattr(buf, 'getvalue'),
                        'Generator should return bytes/bytearray or a file-like object with getvalue()')
