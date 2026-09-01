"""Spec 13: the Celery app, shared by the worker and beat processes.

    celery -A app.workers.celery_app worker -l info
    celery -A app.workers.celery_app beat   -l info   # exactly ONE instance, ever (13.1)

`CELERY_TASK_ALWAYS_EAGER=true` runs tasks inline for local development
(13.3) — turned off before testing anything about background behaviour
itself, since eager mode hides exactly the bugs async execution introduces.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "ems_pro",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.example",
        "app.workers.tasks.attendance",
        "app.workers.tasks.identity",
        "app.workers.tasks.platform",
    ],
)

celery_app.conf.update(
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Route 136's `queued`/`started` distinction needs the worker to report
    # STARTED explicitly — Celery only does this when told to.
    task_track_started=True,
)

# The two scheduled jobs 13.1 names. Both run daily and check their own
# condition per-row/per-company rather than firing once a year, since
# companies can each have their own leave-year rollover date (7.2's
# leave_year_start_month) — a single once-a-year crontab entry would only
# ever be correct for one such date.
celery_app.conf.beat_schedule = {
    "expire-activation-tokens-daily": {
        "task": "app.workers.tasks.identity.expire_activation_tokens",
        "schedule": crontab(hour=2, minute=0),
    },
}
