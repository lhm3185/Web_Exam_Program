from django.urls import path

from . import views

app_name = "exams"

urlpatterns = [
    path("", views.enter_code, name="enter_code"),
    path("exam/", views.student_exam, name="student_exam"),
    path("exam/start/", views.begin_exam, name="begin_exam"),
    path("exam/save/", views.save_exam, name="save_exam"),
    path("exam/exit/", views.exit_exam, name="exit_exam"),
]
