from setuptools import setup, find_packages

setup(
    name="openedx-content-integrity",
    version="0.1.0",
    description="Async plagiarism / AI-authenticity reporting for Open edX course content",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "requests>=2.28",
        "beautifulsoup4>=4.11",
        "lxml>=4.9",
    ],
    # This is the standard Open edX plugin discovery mechanism: edx-platform
    # scans these entry points at startup and wires up apps.py automatically
    # (INSTALLED_APPS, URLs, settings, signal receivers) without you having
    # to hand-edit edx-platform itself.
    entry_points={
        "cms.djangoapp": [
            "content_integrity = content_integrity.apps:ContentIntegrityConfig",
        ],
        "lms.djangoapp": [
            "content_integrity = content_integrity.apps:ContentIntegrityConfig",
        ],
    },
)
