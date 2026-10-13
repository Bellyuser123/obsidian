from django.apps import AppConfig


class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'home'

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(update_default_site, sender=self)


def update_default_site(sender, **kwargs):
    try:
        from django.contrib.sites.models import Site
        from django.conf import settings
        import os
        domain = os.getenv('SITE_DOMAIN', '127.0.0.1:8000')
        Site.objects.filter(id=getattr(settings, 'SITE_ID', 1)).update(
            domain=domain,
            name='Obsidian Arena'
        )
    except Exception:
        pass
