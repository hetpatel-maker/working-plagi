"""
Configure Django settings before any test imports happen.
Mock Open edX platform dependencies that aren't available outside the platform.
"""
import os
import sys
from unittest.mock import MagicMock

# Mock openedx_events and other platform-specific modules before Django setup
# so that apps.py -> receivers.py -> openedx_events doesn't fail.
_platform_modules = [
    "openedx_events",
    "openedx_events.content_authoring",
    "openedx_events.content_authoring.signals",
    "openedx_events.content_authoring.data",
    "celery",
    "opaque_keys",
    "opaque_keys.edx",
    "opaque_keys.edx.keys",
    "common",
    "common.djangoapps",
    "common.djangoapps.student",
    "common.djangoapps.student.roles",
]
for mod_name in _platform_modules:
    if mod_name not in sys.modules:
        mock = MagicMock()
        if mod_name == "celery":
            # shared_task needs to return a decorator that returns the function
            mock.shared_task = lambda *a, **kw: (lambda f: f) if not a else a[0]
        sys.modules[mod_name] = mock

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "content_integrity.tests.test_settings")

import django
django.setup()
