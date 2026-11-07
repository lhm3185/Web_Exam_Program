from os import environ

from django.core.exceptions import ImproperlyConfigured

from .settings import *

domain = environ.get("EXAM_STUDENT_DOMAIN", "").strip().lower()
if not domain or any(char in domain for char in "/: *"):
    raise ImproperlyConfigured("Set EXAM_STUDENT_DOMAIN to the ngrok hostname.")

student_key_path = BASE_DIR / ".student_secret_key"
SECRET_KEY = environ.get("DJANGO_STUDENT_SECRET_KEY", "")
if not SECRET_KEY and student_key_path.is_file():
    SECRET_KEY = student_key_path.read_text(encoding="utf-8").strip()
if len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Generate .student_secret_key before serving students.")

DEBUG = False
ROOT_URLCONF = "config.student_urls"
ALLOWED_HOSTS = [domain]
CSRF_TRUSTED_ORIGINS = [f"https://{domain}"]
SESSION_COOKIE_NAME = "student_exam_session"
CSRF_COOKIE_NAME = "student_exam_csrf"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
