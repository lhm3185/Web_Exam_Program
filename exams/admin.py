from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.forms import BaseInlineFormSet
from django.http import Http404, HttpResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .attempts import close_expired_attempts
from .models import MAX_QUESTIONS, Answer, Attempt, Choice, Exam, ExamAccess, Question


@admin.action(description="선택한 시험지 공개")
def publish_exams(modeladmin, request, queryset):
    published = 0
    for exam_id in queryset.values_list("pk", flat=True):
        try:
            with transaction.atomic():
                exam = Exam.objects.get(pk=exam_id)
                if not exam.published_at:
                    exam.publish()
                    published += 1
        except ValidationError as error:
            modeladmin.message_user(request, error.messages[0], messages.ERROR)
    if published:
        modeladmin.message_user(request, f"시험지 {published}개를 공개했습니다.", messages.SUCCESS)


@admin.action(description="선택한 시험지를 초안으로 복제")
def copy_exams(modeladmin, request, queryset):
    for source in queryset:
        with transaction.atomic():
            copy = Exam.objects.create(
                title=f"{source.title[:195]} (복제)", duration_minutes=source.duration_minutes
            )
            for question in source.questions.prefetch_related("choices"):
                new_question = Question.objects.create(
                    exam=copy, kind=question.kind, prompt=question.prompt, points=question.points,
                    reference_answer=question.reference_answer,
                )
                Choice.objects.bulk_create(
                    Choice(question=new_question, text=choice.text, is_correct=choice.is_correct)
                    for choice in question.choices.all()
                )
        modeladmin.message_user(request, f"'{copy}' 초안을 만들었습니다.", messages.SUCCESS)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "duration_minutes", "published_at")
    readonly_fields = ("published_at",)
    actions = (publish_exams, copy_exams)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        question_admin = self.admin_site.get_model_admin(Question)
        if obj and question_admin.has_view_or_change_permission(request):
            context.update(
                show_exam_questions=True,
                exam_questions=obj.questions.order_by("pk").prefetch_related(
                    Prefetch("choices", queryset=Choice.objects.order_by("pk"))
                ),
                can_add_exam_questions=question_admin.has_add_permission(request),
            )
        return super().render_change_form(request, context, add, change, form_url, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not (obj and obj.published_at)


class QuestionForm(forms.ModelForm):
    class Meta:
        widgets = {"reference_answer": forms.Textarea(attrs={"rows": 7, "class": "vLargeTextField"})}

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("kind") == Question.Kind.MULTIPLE_CHOICE:
            cleaned_data["reference_answer"] = ""
        return cleaned_data

    def clean_exam(self):
        exam = self.cleaned_data["exam"]
        if exam.pk != self.instance.exam_id and exam.questions.count() >= MAX_QUESTIONS:
            raise ValidationError(f"시험지에는 문제를 최대 {MAX_QUESTIONS}개까지 등록할 수 있습니다.")
        return exam


class ChoiceFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        choices = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if self.instance.kind != Question.Kind.MULTIPLE_CHOICE:
            if choices:
                raise ValidationError("주관식과 코딩 문항에서는 보기 입력란을 비워 두세요.")
            return
        if len(choices) < 2:
            raise ValidationError("객관식 보기를 두 개 이상 입력하세요.")
        if sum(choice["is_correct"] for choice in choices) != 1:
            raise ValidationError("정답을 하나만 선택하세요.")


class ChoiceInline(admin.TabularInline):
    model = Choice
    formset = ChoiceFormSet
    extra = 4


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    form = QuestionForm
    fields = ("exam", "kind", "prompt", "points", "reference_answer")
    list_display = ("__str__", "exam", "kind", "points")
    list_filter = ("exam", "kind")
    list_select_related = ("exam",)
    inlines = (ChoiceInline,)

    class Media:
        js = ("exams/question_admin.js",)


class ExamAccessForm(forms.ModelForm):
    def clean(self):
        cleaned_data = super().clean()
        if self.instance._state.adding and not self.errors:
            try:
                self.instance.issue_code()
            except (OSError, ValueError) as error:
                raise ValidationError("응시 코드 저장 키를 확인하세요.") from error
        return cleaned_data


@admin.register(ExamAccess)
class ExamAccessAdmin(admin.ModelAdmin):
    form = ExamAccessForm
    list_display = ("student_name", "exam", "display_code", "is_active")
    list_filter = ("exam", "is_active")
    list_select_related = ("exam",)
    actions = ("replace_legacy_codes",)

    def get_readonly_fields(self, request, obj=None):
        return ("exam", "student_name", "display_code") if obj else ()

    @admin.display(description="응시 코드")
    def display_code(self, obj):
        if not obj.code_seed:
            return "기존 코드 · 교체 필요"
        try:
            return format_html("<code>{}</code>", obj.recover_code())
        except (OSError, ValueError):
            return "응시 코드 저장 키 확인 필요"

    @admin.action(permissions=["change"], description="선택한 기존 응시 코드 교체")
    def replace_legacy_codes(self, request, queryset):
        try:
            with transaction.atomic():
                codes = list(queryset.filter(code_seed=""))
                for access in codes:
                    access.issue_code()
                    access.save(update_fields=["code_seed", "code_digest"])
        except (OSError, ValueError):
            self.message_user(request, "응시 코드 저장 키를 확인하세요.", messages.ERROR)
            return
        if codes:
            self.message_user(
                request, f"기존 응시 코드 {len(codes)}개를 교체했습니다. 목록에서 새 코드를 확인하세요.",
                messages.SUCCESS,
            )
        else:
            self.message_user(request, "선택한 코드에서 교체할 기존 코드를 찾지 못했습니다.", messages.INFO)


class AnswerInline(admin.TabularInline):
    model = Answer
    fields = ("question_prompt", "score", "grade_link")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="답안 및 채점")
    def grade_link(self, obj):
        return format_html('<a href="{}">답안 열기</a>', reverse("admin:exams_answer_change", args=[obj.pk]))


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    fields = (
        "student_name", "access", "exam_title", "state", "started_at", "deadline_at",
        "last_saved_at", "submitted_at", "result",
    )
    readonly_fields = fields
    list_display = ("__str__", "state", "started_at", "deadline_at", "submitted_at", "result")
    list_filter = ("exam",)
    inlines = (AnswerInline,)

    def get_queryset(self, request):
        close_expired_attempts()
        return super().get_queryset(request).select_related("access__exam").annotate(
            total=Sum("answers__score"),
            maximum=Sum("answers__question_points"),
            pending=Count("answers", filter=Q(answers__score__isnull=True)),
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="응시 당시 시험지")
    def exam_title(self, obj):
        return obj.exam_snapshot["title"]

    @admin.display(description="상태")
    def state(self, obj):
        if obj.timed_out:
            return "시간 만료 제출"
        return "제출 완료" if obj.submitted_at else "응시 중"

    @admin.display(description="점수")
    def result(self, obj):
        if not obj.submitted_at:
            return "—"
        score = f"{obj.total or 0}/{obj.maximum}점"
        return f"{score} · 채점 대기 {obj.pending}개" if obj.pending else score


class AnswerForm(forms.ModelForm):
    def clean_score(self):
        score = self.cleaned_data["score"]
        if score is not None and score > self.instance.question_points:
            raise ValidationError("문제 배점 이내로 입력하세요.")
        return score


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    form = AnswerForm
    list_display = ("attempt", "question_prompt", "score")
    list_filter = ("question_kind", "attempt__exam")
    list_select_related = ("attempt",)
    fields = (
        "attempt", "question_prompt", "question_kind", "question_points",
        "expected_answer", "response", "source_link", "score", "feedback",
    )
    readonly_fields = (
        "attempt", "question_prompt", "question_kind", "question_points",
        "expected_answer", "response", "source_link",
    )

    def get_readonly_fields(self, request, obj=None):
        if obj and (obj.question_kind == Question.Kind.MULTIPLE_CHOICE or not obj.text.strip()):
            return (*self.readonly_fields, "score")
        return self.readonly_fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="정답 · 모범 답안")
    def expected_answer(self, obj):
        question = next(
            (question for question in obj.attempt.exam_snapshot["questions"]
             if question["id"] == obj.question_key),
            None,
        )
        if not question:
            return "—"
        if obj.question_kind == Question.Kind.MULTIPLE_CHOICE:
            return ", ".join(choice["text"] for choice in question["choices"] if choice["is_correct"]) or "—"
        answer = question.get("reference_answer")
        return format_html("<pre>{}</pre>", answer) if answer else "—"

    @admin.display(description="학생 답안")
    def response(self, obj):
        if obj.choice_text:
            return obj.choice_text
        return format_html("<pre>{}</pre>", obj.text) if obj.text else "미응답"

    @admin.display(description="Arduino 소스")
    def source_link(self, obj):
        if obj.question_kind == Question.Kind.CODE and obj.text:
            return format_html(
                '<a href="{}">.ino 파일 받기</a>',
                reverse("admin:exams_answer_source", args=[obj.pk]),
            )
        return "—"

    def get_urls(self):
        return [
            path(
                "<int:object_id>/source/",
                self.admin_site.admin_view(self.download_source),
                name="exams_answer_source",
            ),
            *super().get_urls(),
        ]

    def download_source(self, request, object_id):
        answer = self.get_object(request, object_id)
        if not answer or answer.question_kind != Question.Kind.CODE or not answer.text:
            raise Http404
        if not self.has_view_or_change_permission(request, answer):
            raise PermissionDenied
        return HttpResponse(
            answer.text,
            content_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="answer-{answer.pk}.ino"'},
        )


admin.site.site_header = "아두이노 시험 관리"
admin.site.site_title = "아두이노 시험"
admin.site.index_title = "시험지와 응시 기록"
