# Generated manually to add missing fields to SchemeCourse

from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0027_syllabus_cie_marks_data_syllabus_reference_books'),
        ('hod', '0002_combinedsyllabus'),
    ]

    operations = [
        migrations.AddField(
            model_name='schemecourse',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='scheme_courses', to='academics.branch'),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='year',
            field=models.IntegerField(blank=True, help_text='Admission year', null=True),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='course_title',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='category',
            field=models.CharField(blank=True, help_text='BSC, ESC, PCC, PEC, OEC, etc.', max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='is_elective',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='l',
            field=models.IntegerField(default=0, help_text='Lecture hours'),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='t',
            field=models.IntegerField(default=0, help_text='Tutorial hours'),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='p',
            field=models.IntegerField(default=0, help_text='Practical hours'),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='total_hours',
            field=models.IntegerField(blank=True, default=0, null=True),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='cie',
            field=models.IntegerField(default=0, help_text='CIE marks'),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='see',
            field=models.IntegerField(default=0, help_text='SEE marks'),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='total_marks',
            field=models.IntegerField(blank=True, default=0, null=True),
        ),
        migrations.AddField(
            model_name='schemecourse',
            name='credits',
            field=models.DecimalField(blank=True, decimal_places=1, default=Decimal('0.0'), max_digits=4, null=True),
        ),
        migrations.AlterUniqueTogether(
            name='schemecourse',
            unique_together={('branch', 'year', 'semester', 'course_code')},
        ),
        migrations.AddIndex(
            model_name='schemecourse',
            index=models.Index(fields=['branch', 'year', 'semester'], name='hod_schemec_branch__idx'),
        ),
        migrations.AddIndex(
            model_name='schemecourse',
            index=models.Index(fields=['is_elective', 'category'], name='hod_schemec_is_elect_idx'),
        ),
    ]

