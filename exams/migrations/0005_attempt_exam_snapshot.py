from django.db import migrations, models
from django.db.models import Prefetch


def preserve_exam_content(apps, schema_editor):
    Attempt = apps.get_model("exams", "Attempt")
    Answer = apps.get_model("exams", "Answer")
    Question = apps.get_model("exams", "Question")
    Choice = apps.get_model("exams", "Choice")
    database = schema_editor.connection.alias

    choices = Choice.objects.using(database).order_by("pk")
    questions = Question.objects.using(database).order_by("pk").prefetch_related(
        Prefetch("choices", queryset=choices)
    )
    attempts = Attempt.objects.using(database).select_related("access__exam").prefetch_related(
        Prefetch("access__exam__questions", queryset=questions)
    )
    for attempt in attempts.iterator(chunk_size=100):
        exam = attempt.access.exam
        attempt.exam_snapshot = {
            "title": exam.title,
            "duration_minutes": exam.duration_minutes,
            "questions": [
                {
                    "id": question.pk,
                    "kind": question.kind,
                    "prompt": question.prompt,
                    "points": question.points,
                    "choices": [
                        {"id": choice.pk, "text": choice.text, "is_correct": choice.is_correct}
                        for choice in question.choices.all()
                    ],
                }
                for question in exam.questions.all()
            ],
        }
        attempt.save(using=database, update_fields=["exam_snapshot"])

    answers = Answer.objects.using(database).select_related("question", "choice")
    for answer in answers.iterator(chunk_size=100):
        answer.question_key = answer.question_id
        answer.question_kind = answer.question.kind
        answer.question_prompt = answer.question.prompt
        answer.question_points = answer.question.points
        answer.choice_text = answer.choice.text if answer.choice_id else ""
        answer.save(using=database, update_fields=[
            "question_key", "question_kind", "question_prompt", "question_points", "choice_text",
        ])


class Migration(migrations.Migration):
    dependencies = [("exams", "0004_publish_legacy_exams")]

    operations = [
        migrations.AddField(
            model_name="attempt", name="exam_snapshot",
            field=models.JSONField(default=dict, editable=False), preserve_default=False,
        ),
        migrations.AddField(
            model_name="answer", name="question_key",
            field=models.PositiveBigIntegerField(default=0, editable=False), preserve_default=False,
        ),
        migrations.AddField(
            model_name="answer", name="question_kind",
            field=models.CharField(
                "문제 유형", max_length=10, default="choice",
                choices=[("choice", "객관식"), ("written", "주관식"), ("code", "코딩")],
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="answer", name="question_prompt",
            field=models.TextField("문제", default=""), preserve_default=False,
        ),
        migrations.AddField(
            model_name="answer", name="question_points",
            field=models.PositiveSmallIntegerField("배점", default=0), preserve_default=False,
        ),
        migrations.AddField(
            model_name="answer", name="choice_text",
            field=models.CharField("선택한 보기", max_length=500, blank=True, default=""),
            preserve_default=False,
        ),
        migrations.RunPython(preserve_exam_content),
        migrations.RemoveConstraint(model_name="answer", name="one_answer_per_question"),
        migrations.RemoveField(model_name="answer", name="choice"),
        migrations.RemoveField(model_name="answer", name="question"),
        migrations.AddConstraint(
            model_name="answer",
            constraint=models.UniqueConstraint(
                fields=["attempt", "question_key"], name="one_answer_per_snapshot_question"
            ),
        ),
    ]
