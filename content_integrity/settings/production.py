def plugin_settings(settings):
    # In production these come from your env config (lms.yml/cms.yml under
    # Tutor, or AUTH_TOKENS/ENV_TOKENS for native installs) — never commit
    # real API keys to this file.
    settings.CONTENT_INTEGRITY_PROVIDER = settings.ENV_TOKENS.get(
        "CONTENT_INTEGRITY_PROVIDER", settings.CONTENT_INTEGRITY_PROVIDER
    )
    settings.CONTENT_INTEGRITY_FLAG_THRESHOLD = settings.ENV_TOKENS.get(
        "CONTENT_INTEGRITY_FLAG_THRESHOLD", settings.CONTENT_INTEGRITY_FLAG_THRESHOLD
    )
    settings.CONTENT_INTEGRITY_PLAGIARISMCHECK_API_TOKEN = settings.AUTH_TOKENS.get(
        "CONTENT_INTEGRITY_PLAGIARISMCHECK_API_TOKEN", ""
    )
    settings.CONTENT_INTEGRITY_COPYLEAKS_EMAIL = settings.ENV_TOKENS.get(
        "CONTENT_INTEGRITY_COPYLEAKS_EMAIL", ""
    )
    settings.CONTENT_INTEGRITY_COPYLEAKS_API_KEY = settings.AUTH_TOKENS.get(
        "CONTENT_INTEGRITY_COPYLEAKS_API_KEY", ""
    )
    settings.CONTENT_INTEGRITY_COPYLEAKS_SANDBOX = settings.ENV_TOKENS.get(
        "CONTENT_INTEGRITY_COPYLEAKS_SANDBOX", True
    )
    settings.CONTENT_INTEGRITY_CMS_ROOT_URL = settings.ENV_TOKENS.get(
        "CMS_ROOT_URL", getattr(settings, "CMS_ROOT_URL", "")
    )
