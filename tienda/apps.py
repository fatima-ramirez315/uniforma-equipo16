from django.apps import AppConfig
from django.db.models.signals import post_migrate


class TiendaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tienda"

    def ready(self):
        from .demo import autoseed

        post_migrate.connect(autoseed, sender=self, dispatch_uid="tienda_autoseed")
