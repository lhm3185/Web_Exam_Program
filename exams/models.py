from secrets import token_hex

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from .access_codes import access_code_digest, access_code_key, create_access_code_key, derive_access_code

MAX_QUESTIONS = 30
MAX_ANSWER_LENGTH = 5000


class Exam(models.Model):
    title = models.CharField("제목", max_length=200)
    duration_minutes = models.PositiveSmallIntegerField(
        "제한 시간(분)", default=30, validators=[MinValueValidator(1)]
    )
    published_at = models.DateTimeField("공개 시각", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "시험지"
        verbose_name_plural = "시험지"

    def __str__(self):
        return self.title

    def validated_questions(self):
        choices_by_id = Choice.objects.order_by("pk")
        questions = list(
            self.questions.order_by("pk").prefetch_related(
                models.Prefetch("choices", queryset=choices_by_id)
            )[:MAX_QUESTIONS + 1]
        )
        if not 1 <= len(questions) <= MAX_QUESTIONS:
            raise ValidationError(f"시험지에 문제를 1개 이상 {MAX_QUESTIONS}개 이하로 등록하세요.")
        for question in questions:
            choices = list(question.choices.all())
            if question.kind == Question.Kind.MULTIPLE_CHOICE:
                if len(choices) < 2 or sum(choice.is_correct for choice in choices) != 1:
                    raise ValidationError(f"'{question}'의 보기와 정답을 확인하세요.")
            elif choices:
                raise ValidationError(f"'{question}'에서 객관식 보기를 삭제하세요.")
        return questions

    def publish(self):
        self.validated_questions()
        self.published_at = timezone.now()
        self.save(update_fields=["published_at"])


class Question(models.Model):
    class Kind(models.TextChoices):
        MULTIPLE_CHOICE = "choice", "객관식"
        WRITTEN = "written", "주관식"
        CODE = "code", "코딩"

    exam = models.ForeignKey(
        Exam, on_delete=models.CASCADE, related_name="questions", verbose_name="시험지"
    )
    kind = models.CharField("문제 유형", max_length=10, choices=Kind, default=Kind.MULTIPLE_CHOICE)
    prompt = models.TextField("문제")
    reference_answer = models.TextField("모범 답안", blank=True)
    points = models.PositiveSmallIntegerField(
        "배점", default=1, validators=[MinValueValidator(1)]
    )

    class Meta:
        verbose_name = "문제"
        verbose_name_plural = "문제"

    def __str__(self):
        return self.prompt[:80]


class Choice(models.Model):
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="choices", verbose_name="문제"
    )
    text = models.CharField("보기 내용", max_length=500)
    is_correct = models.BooleanField("정답", default=False)

    class Meta:
        verbose_name = "보기"
        verbose_name_plural = "보기"

    def __str__(self):
        return self.text


class ExamAccess(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, verbose_name="시험지")
    student_name = models.CharField("학생 이름", max_length=100)
    code_digest = models.CharField(max_length=64, unique=True, editable=False)
    code_seed = models.CharField(max_length=32, blank=True, editable=False)
    is_active = models.BooleanField("사용 가능", default=True)

    class Meta:
        verbose_name = "응시 코드"
        verbose_name_plural = "응시 코드"

    def __str__(self):
        return f"{self.student_name} · {self.exam}"

    def issue_code(self):
        try:
            key = access_code_key()
        except FileNotFoundError:
            if type(self).objects.exclude(code_seed="").exists():
                raise
            key = create_access_code_key()

        self.code_seed = token_hex(16)
        self.code_digest = access_code_digest(derive_access_code(self.code_seed, key))

    def recover_code(self):
        code = derive_access_code(self.code_seed, access_code_key())
        if access_code_digest(code) != self.code_digest:
            raise ValueError("Access code does not match the stored digest.")
        return code


class Attempt(models.Model):
    access = models.OneToOneField(
        ExamAccess, on_delete=models.SET_NULL, related_name="attempt",
        null=True, blank=True, verbose_name="응시 코드",
    )
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, verbose_name="시험지")
    student_name = models.CharField("학생 이름", max_length=100)
    exam_snapshot = models.JSONField(editable=False)
    started_at = models.DateTimeField("시작 시각")
    deadline_at = models.DateTimeField("마감 시각", db_index=True)
    last_saved_at = models.DateTimeField("마지막 저장 시각", null=True, blank=True)
    submitted_at = models.DateTimeField("제출 시각", null=True, blank=True)
    timed_out = models.BooleanField("시간 만료", default=False)
    draft = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "응시 기록"
        verbose_name_plural = "응시 기록"

    def __str__(self):
        return f"{self.student_name} · {self.exam_snapshot['title']}"


class Answer(models.Model):
    attempt = models.ForeignKey(
        Attempt, on_delete=models.CASCADE, related_name="answers", verbose_name="응시 기록"
    )
    question_key = models.PositiveBigIntegerField(editable=False)
    question_kind = models.CharField("문제 유형", max_length=10, choices=Question.Kind)
    question_prompt = models.TextField("문제")
    question_points = models.PositiveSmallIntegerField("배점")
    choice_text = models.CharField("선택한 보기", max_length=500, blank=True)
    text = models.TextField("입력한 답안", blank=True)
    score = models.PositiveSmallIntegerField("점수", null=True, blank=True)
    feedback = models.TextField("피드백", blank=True)

    class Meta:
        verbose_name = "제출 답안"
        verbose_name_plural = "제출 답안"
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question_key"], name="one_answer_per_snapshot_question"
            )
        ]

    def __str__(self):
        return f"{self.attempt} · {self.question_prompt[:80]}"
