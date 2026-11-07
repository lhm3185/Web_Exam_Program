from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exams", "0006_access_management")]

    operations = [
        migrations.AddField(
            model_name="question",
            name="reference_answer",
            field=models.TextField("모범 답안", blank=True),
        ),
    ]
