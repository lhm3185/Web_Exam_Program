import django.db.models.deletion
from django.db import migrations, models


def preserve_attempt_identity(apps, schema_editor):
    Attempt = apps.get_model("exams", "Attempt")
    database = schema_editor.connection.alias
    attempts = Attempt.objects.using(database).select_related("access")
    for attempt in attempts.iterator(chunk_size=100):
        attempt.exam_id = attempt.access.exam_id
        attempt.student_name = attempt.access.student_name
        attempt.save(using=database, update_fields=["exam", "student_name"])


class Migration(migrations.Migration):
    dependencies = [("exams", "0005_attempt_exam_snapshot")]

    operations = [
        migrations.AddField(
            model_name="examaccess",
            name="code_seed",
            field=models.CharField(blank=True, default="", editable=False, max_length=32),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="attempt",
            name="exam",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                to="exams.exam", verbose_name="시험지",
            ),
        ),
        migrations.AddField(
            model_name="attempt",
            name="student_name",
            field=models.CharField(default="", max_length=100, verbose_name="학생 이름"),
            preserve_default=False,
        ),
        migrations.RunPython(preserve_attempt_identity),
        migrations.AlterField(
            model_name="attempt",
            name="exam",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="exams.exam", verbose_name="시험지",
            ),
        ),
        migrations.AlterField(
            model_name="attempt",
            name="access",
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="attempt", to="exams.examaccess", verbose_name="응시 코드",
            ),
        ),
    ]
