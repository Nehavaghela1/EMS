"""A trivial task with no side effects, no database, nothing tenant-shaped —
the one thing WP-09's gate asks be proven working before anything real is
built on top of the worker: that a task queued via `.delay()` actually
completes asynchronously while the caller stays responsive.
"""

from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.example.add")
def add(x: int, y: int) -> int:
    return x + y
