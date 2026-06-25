"""
Minimal Django settings for running tests outside the Open edX platform.
"""
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "content_integrity",
]

SECRET_KEY = "test-secret-key-not-for-production"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Content integrity settings
LMS_ROOT_URL = "http://localhost:18000"
CMS_ROOT_URL = "http://localhost:18010"
BACKEND_SERVICE_EDX_OAUTH2_KEY = "test-key"
BACKEND_SERVICE_EDX_OAUTH2_SECRET = "test-secret"
CONTENT_INTEGRITY_PROVIDER = "plagiarismcheck"
CONTENT_INTEGRITY_FLAG_THRESHOLD = 20.0
CONTENT_INTEGRITY_PLAGIARISMCHECK_API_TOKEN = "test-token"
CONTENT_INTEGRITY_COPYLEAKS_EMAIL = ""
CONTENT_INTEGRITY_COPYLEAKS_API_KEY = ""
