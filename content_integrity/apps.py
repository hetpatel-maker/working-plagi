"""
App config for the content_integrity plugin.

Registered against both cms.djangoapp (Studio, where publishing happens)
and lms.djangoapp (so the report API can also be exposed on the LMS side
if you want learners' staff/instructor views to read it from there too).

NOTE: the `plugin_app` dict format below follows the conventions documented
at https://docs.openedx.org/projects/edx-platform/en/latest/references/plugins.html
Field names are stable across recent releases (Redwood/Sumac/Teak) but it's
worth a quick diff against that doc for whatever release you're actually on.
"""
from django.apps import AppConfig


class ContentIntegrityConfig(AppConfig):
    name = "content_integrity"
    verbose_name = "Content Integrity (Plagiarism & Authenticity Checks)"

    plugin_app = {
        "url_config": {
            "cms.djangoapp": {
                "namespace": "content_integrity",
                "regex": r"^api/content-integrity/",
                "relative_path": "api.urls",
            },
            "lms.djangoapp": {
                "namespace": "content_integrity",
                "regex": r"^api/content-integrity/",
                "relative_path": "api.urls",
            },
        },
        "settings_config": {
            "cms.djangoapp": {
                "common": {"relative_path": "settings.common"},
                "production": {"relative_path": "settings.production"},
            },
            "lms.djangoapp": {
                "common": {"relative_path": "settings.common"},
                "production": {"relative_path": "settings.production"},
            },
        },
    }

    def ready(self):
        # Importing this module is what actually connects the @receiver-decorated
        # functions in receivers.py to the openedx-events signals. Doing it here
        # (rather than at module import time elsewhere) guarantees Django's app
        # registry is fully loaded first.
        print("\n" + "="*60)
        print("🚀 CONTENT INTEGRITY PLUGIN IS LOADING IN THIS CONTAINER! 🚀")
        print("="*60 + "\n")
        from . import receivers  # noqa: F401
