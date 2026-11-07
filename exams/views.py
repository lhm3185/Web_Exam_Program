from django import forms
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from .access_codes import access_code_digest
from .attempts import StaleDraft, close_if_expired, save_attempt, start_attempt
from .models import Attempt, ExamAccess, MAX_ANSWER_LENGTH, Question

ACCESS_SESSION_KEY = "exam_access_id"


class AccessCodeForm(forms.Form):
    code = forms.RegexField(
        r"\A[0-9a-fA-F]{24}\Z",
        label="응시 코드",
        widget=forms.PasswordInput(
            attrs={"autocomplete": "off", "autocapitalize": "none", "spellcheck": "false"}
        ),
        error_messages={"required": "응시 코드를 입력하세요.", "invalid": "응시 코드를 확인하세요."},
    )


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def enter_code(request):
    form = AccessCodeForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        access = ExamAccess.objects.filter(
            code_digest=access_code_digest(form.cleaned_data["code"]), is_active=True
        ).first()
        if access:
            request.session.cycle_key()
            request.session[ACCESS_SESSION_KEY] = access.pk
            return redirect("exams:student_exam")
        form.add_error("code", "응시 코드를 확인하세요.")

    return render(request, "exams/enter_code.html", {"form": form})


@never_cache
@require_safe
def student_exam(request):
    access = ExamAccess.objects.select_related("exam").filter(
        pk=request.session.get(ACCESS_SESSION_KEY), is_active=True
    ).first()
    if not access:
        request.session.pop(ACCESS_SESSION_KEY, None)
        return redirect("exams:enter_code")

    attempt = Attempt.objects.filter(access=access).first()
    if attempt and not attempt.submitted_at and timezone.now() >= attempt.deadline_at:
        attempt = close_if_expired(attempt.pk)
    context = {
        "exam": (
            {
                "title": attempt.exam_snapshot["title"],
                "duration_minutes": attempt.exam_snapshot["duration_minutes"],
            }
            if attempt else access.exam
        ),
        "student_name": access.student_name,
        "attempt": attempt,
    }
    if not attempt and access.exam.published_at:
        try:
            access.exam.validated_questions()
        except ValidationError:
            context["exam_ready"] = False
        else:
            context["exam_ready"] = True
    if not attempt or attempt.submitted_at:
        return render(request, "exams/exam_status.html", context)

    questions = []
    for question in attempt.exam_snapshot["questions"]:
        student_question = {
            "id": question["id"],
            "kind": question["kind"],
            "kind_label": Question.Kind(question["kind"]).label,
            "prompt": question["prompt"],
            "points": question["points"],
            "choices": [
                {"id": choice["id"], "text": choice["text"]} for choice in question["choices"]
            ],
        }
        questions.append((student_question, attempt.draft.get(str(question["id"]), "")))

    context.update(
        questions=questions,
        max_answer_length=MAX_ANSWER_LENGTH,
        remaining_ms=max(0, int((attempt.deadline_at - timezone.now()).total_seconds() * 1000)),
    )
    return render(request, "exams/student_exam.html", context)


@require_POST
def begin_exam(request):
    try:
        start_attempt(request.session.get(ACCESS_SESSION_KEY))
    except ExamAccess.DoesNotExist:
        return redirect("exams:enter_code")
    except ValidationError:
        return redirect("exams:student_exam")
    return redirect("exams:student_exam")


@never_cache
@require_POST
def save_exam(request):
    action = request.POST.get("action")
    if action not in {"save", "submit"}:
        return JsonResponse({"error": "저장 또는 제출을 선택하세요."}, status=400)

    use_json = request.headers.get("Accept") == "application/json"
    try:
        attempt = save_attempt(
            request.session.get(ACCESS_SESSION_KEY), request.POST, submit=action == "submit"
        )
    except Attempt.DoesNotExist:
        if use_json:
            return JsonResponse({"error": "응시 코드로 다시 접속하세요."}, status=403)
        return redirect("exams:student_exam")
    except ValidationError as error:
        status = 409 if isinstance(error, StaleDraft) else 400
        if use_json:
            return JsonResponse({"error": error.messages[0]}, status=status)
        return render(request, "exams/save_error.html", {"error": error.messages[0]}, status=status)

    if not use_json:
        return redirect("exams:student_exam")
    return JsonResponse({
        "revision": attempt.revision,
        "submitted": attempt.submitted_at is not None,
        "remaining_ms": max(0, int((attempt.deadline_at - timezone.now()).total_seconds() * 1000)),
        "exam_url": reverse("exams:student_exam"),
    })


@require_POST
def exit_exam(request):
    request.session.pop(ACCESS_SESSION_KEY, None)
    return redirect("exams:enter_code")
