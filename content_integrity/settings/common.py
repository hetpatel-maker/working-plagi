"""
Open edX's plugin loader calls plugin_settings(settings) automatically for
every app listed under settings_config in apps.py — you don't import this
manually anywhere. Override the real values via your deployment's env
config (lms.yml / cms.yml, or Tutor plugin patches) rather than editing
this file directly.
"""


def plugin_settings(settings):
    # "plagiarismcheck" or "copyleaks" — see providers/__init__.py
    settings.CONTENT_INTEGRITY_PROVIDER = "copyleaks"

    # Similarity percentage at/above which a block is marked FLAGGED rather than CLEAN.
    settings.CONTENT_INTEGRITY_FLAG_THRESHOLD = 20.0

    if not getattr(settings, "CONTENT_INTEGRITY_PLAGIARISMCHECK_API_TOKEN", ""):
        settings.CONTENT_INTEGRITY_PLAGIARISMCHECK_API_TOKEN = ""
    if not getattr(settings, "CONTENT_INTEGRITY_COPYLEAKS_EMAIL", ""):
        settings.CONTENT_INTEGRITY_COPYLEAKS_EMAIL = ""
    if not getattr(settings, "CONTENT_INTEGRITY_COPYLEAKS_API_KEY", ""):
        settings.CONTENT_INTEGRITY_COPYLEAKS_API_KEY = ""

    # Sandbox mode — True means Copyleaks returns fake (but realistic) results
    # at zero cost. Set to False in production when you want real scans.
    settings.CONTENT_INTEGRITY_COPYLEAKS_SANDBOX = True

    # CMS (Studio) root URL
    settings.CONTENT_INTEGRITY_CMS_ROOT_URL = getattr(settings, "CMS_ROOT_URL", "")

    # Fallback for OAuth2 keys if they are not defined in the environment (common in local dev)
    if not hasattr(settings, "BACKEND_SERVICE_EDX_OAUTH2_KEY"):
        settings.BACKEND_SERVICE_EDX_OAUTH2_KEY = "dev-oauth2-key"
    if not hasattr(settings, "BACKEND_SERVICE_EDX_OAUTH2_SECRET"):
        settings.BACKEND_SERVICE_EDX_OAUTH2_SECRET = "dev-oauth2-secret"
