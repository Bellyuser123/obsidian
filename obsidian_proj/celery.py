import os
from celery import Celery

# Set default Django settings module for celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'obsidian_proj.settings')

app = Celery('obsidian_proj')

# Load settings from django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Discover tasks in apps
app.autodiscover_tasks()

# ------------------------------------------------------------------------------
# Celery Database Connection Hygiene
# Prevent connection leaks and pool starvation under heavy contest submission load.
# In worker threads, Django does not have HTTP request_finished signals to trigger
# connection closure; connections must be released explicitly to dj_db_conn_pool.
# ------------------------------------------------------------------------------
from celery.signals import task_prerun, task_postrun

@task_prerun.connect
def on_task_prerun(*args, **kwargs):
    from django.db import close_old_connections
    close_old_connections()

@task_postrun.connect
def on_task_postrun(*args, **kwargs):
    from django.db import close_old_connections, connections
    for conn in connections.all(initialized_only=True):
        try:
            conn.close()
        except Exception:
            pass
    close_old_connections()
