from django.apps import AppConfig


class ParletreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parletre"
    verbose_name = "Parlêtre (discussion)"

    def ready(self):
        from . import signals  # noqa: F401  (registers the workgroup-channel provisioner)
