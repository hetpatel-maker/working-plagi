from django.conf import settings

from .base import PlagiarismProvider  # noqa: F401  (re-exported for convenience)
from .plagiarismcheck import PlagiarismCheckProvider
from .copyleaks import CopyleaksProvider

_PROVIDERS = {
    "plagiarismcheck": PlagiarismCheckProvider,
    "copyleaks": CopyleaksProvider,
}


def get_provider() -> PlagiarismProvider:
    """
    Single switch point for which vendor is active. Change
    CONTENT_INTEGRITY_PROVIDER in settings and every task/view that calls
    get_provider() switches automatically — nothing else in the codebase
    needs to know which vendor is behind it.
    """
    provider_key = getattr(settings, "CONTENT_INTEGRITY_PROVIDER", "plagiarismcheck")
    provider_cls = _PROVIDERS.get(provider_key)
    if not provider_cls:
        raise ValueError(f"Unknown CONTENT_INTEGRITY_PROVIDER: {provider_key!r}")
    return provider_cls()
