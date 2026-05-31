import os
from celery import Celery

# Set default Django settings module for celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'obsidian_proj.settings')

app = Celery('obsidian_proj')

# Load settings from django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Discover tasks in apps
app.autodiscover_tasks()
