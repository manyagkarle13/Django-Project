from django.apps import AppConfig


class AcademicsConfig(AppConfig):
    # Make sure the name is your app package name (likely 'academics')
    name = "academics"

    def ready(self):
        # Import signals in ready — but guard to avoid import-time errors during migrations/test
        try:
            import academics.signals  # noqa: F401
        except Exception:
            # Avoid failing app loading if signals import fails (will surface later)
            # You can log here if you want
            pass
