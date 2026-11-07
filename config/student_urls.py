from pathlib import Path

from django.http import FileResponse
from django.urls import include, path
from django.views.decorators.http import require_safe

STUDENT_ASSETS = Path(__file__).resolve().parent.parent / "exams" / "static" / "exams"


@require_safe
def student_asset(request, filename, content_type):
    return FileResponse(
        (STUDENT_ASSETS / filename).open("rb"),
        content_type=content_type,
        headers={"Cache-Control": "no-cache"},
    )


urlpatterns = [
    path("", include("exams.urls")),
    path("static/exams/student.css", student_asset, {"filename": "student.css", "content_type": "text/css"}),
    path("static/exams/attempt.css", student_asset, {"filename": "attempt.css", "content_type": "text/css"}),
    path("static/exams/student.js", student_asset, {"filename": "student.js", "content_type": "text/javascript"}),
]
