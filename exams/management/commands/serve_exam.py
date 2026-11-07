import logging
from threading import Event, Thread

from django.conf import settings
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.management.base import BaseCommand, CommandError
from django.core.wsgi import get_wsgi_application
from django.db import OperationalError, close_old_connections

from exams.attempts import close_expired_attempts

logger = logging.getLogger(__name__)


def finalize_on_schedule(stop):
    while not stop.is_set():
        close_old_connections()
        try:
            close_expired_attempts()
        except OperationalError:
            logger.exception("Could not finalize expired exams; retrying.")
        finally:
            close_old_connections()
        stop.wait(2)


class Command(BaseCommand):
    help = "Serve this exam site on loopback and finalize expired attempts."

    def handle(self, *args, **options):
        try:
            from waitress import serve
        except ImportError as error:
            raise CommandError("Install requirements.txt before starting the server.") from error

        public = settings.ROOT_URLCONF == "config.student_urls"
        port = 8001 if public else 8000
        application = get_wsgi_application()
        if not public:
            application = StaticFilesHandler(application)

        stop = Event()
        worker = Thread(target=finalize_on_schedule, args=(stop,), daemon=True)
        worker.start()
        self.stdout.write(f"Exam server listening on 127.0.0.1:{port}")
        try:
            serve(
                application,
                listen=f"127.0.0.1:{port}",
                url_scheme="https" if public else "http",
                max_request_body_size=3 * 1024 * 1024,
            )
        finally:
            stop.set()
