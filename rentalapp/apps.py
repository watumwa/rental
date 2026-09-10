from django.apps import AppConfig


class RentalappConfig(AppConfig):
    name = 'rentalapp'

    def ready(self):
        from . import signals  # noqa: F401
