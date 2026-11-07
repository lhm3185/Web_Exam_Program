from django.db import migrations
from django.utils import timezone


def publish_legacy_exams(apps, schema_editor):
    Exam = apps.get_model("exams", "Exam")
    ExamAccess = apps.get_model("exams", "ExamAccess")
    database = schema_editor.connection.alias
    exams = Exam.objects.using(database).filter(
        pk__in=ExamAccess.objects.using(database).values("exam_id")
    ).prefetch_related("questions__choices")
    for exam in exams:
        questions = list(exam.questions.all())
        if 1 <= len(questions) <= 30 and all(
            len(question.choices.all()) >= 2
            and sum(choice.is_correct for choice in question.choices.all()) == 1
            for question in questions
        ):
            exam.published_at = timezone.now()
            exam.save(using=database, update_fields=["published_at"])


class Migration(migrations.Migration):
    dependencies = [("exams", "0003_exam_workflow")]
    operations = [migrations.RunPython(publish_legacy_exams, migrations.RunPython.noop)]
