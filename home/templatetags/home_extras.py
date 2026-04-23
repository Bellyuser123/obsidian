from django import template
from django.utils import timezone

register = template.Library()

@register.filter(name='split')
def split(value, arg):
    return value.split(arg)

@register.filter(name='trim')
def trim(value):
    return value.strip()

@register.filter(name='duration')
def duration(start_time, end_time):
    if not start_time or not end_time:
        return ""
    diff = end_time - start_time
    total_seconds = int(diff.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
