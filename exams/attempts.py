from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Answer, Attempt, ExamAccess, MAX_ANSWER_LENGTH, Question


class StaleDraft(ValidationError):
    pass


@transaction.atomic
def start_attempt(access_id):
    access = ExamAccess.objects.select_related("exam").get(pk=access_id, is_active=True)
    attempt = Attempt.objects.filter(access=access).first()
    if attempt:
        return attempt
    if not access.exam.published_at:
        return None

    exam = access.exam
    questions = exam.validated_questions()
    snapshot = {
        "title": exam.title,
        "duration_minutes": exam.duration_minutes,
        "questions": [
            {
                "id": question.pk,
                "kind": question.kind,
                "prompt": question.prompt,
                "reference_answer": question.reference_answer,
                "points": question.points,
                "choices": [
                    {"id": choice.pk, "text": choice.text, "is_correct": choice.is_correct}
                    for choice in question.choices.all()
                ],
            }
            for question in questions
        ],
    }
    now = timezone.now()
    return Attempt.objects.create(
        access=access,
        exam=exam,
        student_name=access.student_name,
        exam_snapshot=snapshot,
        started_at=now,
        deadline_at=now + timedelta(minutes=exam.duration_minutes),
    )


def collect_draft(questions, data):
    draft = {}
    for question in questions:
        question_id = question["id"]
        value = data.get(f"answer_{question_id}", "")
        if question["kind"] == Question.Kind.MULTIPLE_CHOICE:
            if value and value not in {str(choice["id"]) for choice in question["choices"]}:
                raise ValidationError("선택한 보기를 확인하세요.")
        elif len(value) > MAX_ANSWER_LENGTH:
            raise ValidationError(f"답안은 한 문제당 {MAX_ANSWER_LENGTH}자까지 입력할 수 있습니다.")
        if value:
            draft[str(question_id)] = value
    return draft


def finalize(attempt, now, *, timed_out):
    answers = []
    for question in attempt.exam_snapshot["questions"]:
        value = attempt.draft.get(str(question["id"]), "")
        answer = Answer(
            attempt=attempt,
            question_key=question["id"],
            question_kind=question["kind"],
            question_prompt=question["prompt"],
            question_points=question["points"],
        )
        if question["kind"] == Question.Kind.MULTIPLE_CHOICE:
            selected = next(
                (choice for choice in question["choices"] if str(choice["id"]) == value), None
            )
            answer.choice_text = selected["text"] if selected else ""
            answer.score = question["points"] if selected and selected["is_correct"] else 0
        else:
            answer.text = value
            answer.score = None if value.strip() else 0
        answers.append(answer)

    Answer.objects.bulk_create(answers)
    attempt.submitted_at = attempt.deadline_at if timed_out else now
    attempt.timed_out = timed_out
    attempt.draft = {}
    attempt.save(update_fields=["submitted_at", "timed_out", "draft"])


@transaction.atomic
def save_attempt(access_id, data, *, submit):
    attempt = Attempt.objects.get(access_id=access_id, access__is_active=True)
    if attempt.submitted_at:
        return attempt

    now = timezone.now()
    if now >= attempt.deadline_at:
        finalize(attempt, now, timed_out=True)
        return attempt

    if data.get("revision") != str(attempt.revision):
        raise StaleDraft("다른 창에서 답안이 갱신됐습니다. 시험 화면을 새로고침하세요.")

    attempt.draft = collect_draft(attempt.exam_snapshot["questions"], data)
    attempt.revision += 1
    attempt.last_saved_at = now
    attempt.save(update_fields=["draft", "revision", "last_saved_at"])
    if submit:
        finalize(attempt, now, timed_out=False)
    return attempt


@transaction.atomic
def close_if_expired(attempt_id):
    attempt = Attempt.objects.get(pk=attempt_id)
    now = timezone.now()
    if not attempt.submitted_at and now >= attempt.deadline_at:
        finalize(attempt, now, timed_out=True)
    return attempt


def close_expired_attempts():
    expired = Attempt.objects.filter(
        submitted_at__isnull=True, deadline_at__lte=timezone.now()
    ).values_list("pk", flat=True)
    for attempt_id in list(expired):
        close_if_expired(attempt_id)
