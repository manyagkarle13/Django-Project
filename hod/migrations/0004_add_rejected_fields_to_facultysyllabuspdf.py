# Generated manually to add rejected fields to FacultySyllabusPDF

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('hod', '0003_add_schemecourse_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='facultysyllabuspdf',
            name='rejected',
            field=models.BooleanField(default=False, help_text='Marked as rejected by HOD'),
        ),
        migrations.AddField(
            model_name='facultysyllabuspdf',
            name='rejected_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='facultysyllabuspdf',
            name='rejected_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='rejected_faculty_pdfs', to=settings.AUTH_USER_MODEL),
        ),
    ]

