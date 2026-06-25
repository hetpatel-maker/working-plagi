"""
Connects to the platform's own publish events. XBLOCK_PUBLISHED fires every
time a course author publishes content in Studio — but critically, if a
parent block (section, unit, chapter) is published with changes in child
blocks, the system fires a **single** event containing the parent's
usage_key, NOT one event per child.

This means the handler must detect container blocks and enumerate all
checkable children inside them via the Blocks API, rather than treating
every event as a single-block event.

Signal handlers MUST stay fast — they run synchronously in the same
request as the publish action. All we do here is enqueue Celery tasks.

NOTE: In Tutor dev mode, CELERY_TASK_ALWAYS_EAGER=True causes .delay()
to run synchronously in the HTTP thread. This will block the Publish
button while Copyleaks polls. In production, a real Celery worker
handles these tasks asynchronously with no blocking.
"""
import logging

from django.dispatch import receiver
from openedx_events.content_authoring.signals import XBLOCK_PUBLISHED, XBLOCK_DELETED

try:
    # pyrefly: ignore [missing-import]
    from xmodule.modulestore.django import SignalHandler
    course_published = SignalHandler.course_published
except ImportError:
    course_published = None

from .tasks import process_block_publish, process_block_deletion, enqueue_children_checks

log = logging.getLogger(__name__)

# Block types that are containers (have children but no checkable text themselves).
# When one of these is published, we need to enumerate all checkable children.
CONTAINER_BLOCK_TYPES = frozenset({
    "course", "chapter", "sequential", "vertical",
})

# Block types that contain checkable text content.
CHECKABLE_BLOCK_TYPES = frozenset({
    "html", "problem", "video", "openassessment",
})


@receiver(XBLOCK_PUBLISHED)
def on_xblock_published(sender, xblock_info=None, **kwargs):
    if xblock_info is None:
        log.warning("[content_integrity] XBLOCK_PUBLISHED received with no xblock_info payload, ignoring")
        return

    usage_key = str(xblock_info.usage_key)
    block_type = getattr(xblock_info, "block_type", None) or xblock_info.usage_key.block_type
    course_key = getattr(xblock_info, "course_key", None) or xblock_info.usage_key.course_key
    course_id = str(course_key)

    log.info(
        "[content_integrity] XBLOCK_PUBLISHED signal received: usage_key=%s, block_type=%s, course_id=%s",
        usage_key, block_type, course_id,
    )

    if block_type in CONTAINER_BLOCK_TYPES:
        # Parent block published — we need to find and check all checkable
        # children. This is done asynchronously in a Celery task to keep
        # the signal handler fast.
        log.info(
            "[content_integrity] Container block %s (%s) published — enqueuing child enumeration for course %s",
            usage_key, block_type, course_id,
        )
        enqueue_children_checks.delay(course_id=course_id)
    elif block_type in CHECKABLE_BLOCK_TYPES:
        # Leaf block with checkable content — queue it directly.
        log.info(
            "[content_integrity] Checkable block %s (%s) published — enqueuing plagiarism check",
            usage_key, block_type,
        )
        process_block_publish.delay(
            usage_key=usage_key, course_id=course_id, block_type=block_type,
        )
    else:
        # Some other block type we don't handle (e.g. discussion, openassessment).
        # Log but don't enqueue — it would just get SKIPPED anyway.
        log.debug(
            "[content_integrity] Ignoring XBLOCK_PUBLISHED for unhandled block_type=%s (%s)",
            block_type, usage_key,
        )


@receiver(XBLOCK_DELETED)
def on_xblock_deleted(sender, xblock_info=None, **kwargs):
    if xblock_info is None:
        log.warning("[content_integrity] XBLOCK_DELETED received with no xblock_info, ignoring")
        return
    usage_key = str(xblock_info.usage_key)
    log.info("[content_integrity] XBLOCK_DELETED signal: deleting ContentCheck for %s", usage_key)
    process_block_deletion.delay(usage_key=usage_key)

if course_published:
    @receiver(course_published)
    def on_course_published(sender, course_key=None, **kwargs):
        if course_key is None:
            return
        log.info(
            "[content_integrity] course_published signal for %s — enqueuing check for ALL blocks",
            course_key,
        )
        enqueue_children_checks.delay(course_id=str(course_key))
