"""
The actual pipeline:

  process_block_publish   -> extract text, hash it, compare to stored hash.
                              Unchanged? stop here. Changed? hand off to:
  run_plagiarism_check    -> call the provider, store the result.
                              Either way, kick off:
  refresh_course_report   -> cheap DB aggregation, rebuilds the course-level
                              summary from current ContentCheck rows.

  enqueue_children_checks -> called when a container block is published;
                              enumerates all checkable children via the
                              Blocks API and enqueues a task for each one.

Split into separate tasks so a flaky external API call can retry/fail
independently of the cheap local extraction+hashing work, and so the
report rollup runs even when nothing changed.
"""
import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .extraction import fetch_block_content, extract_plain_text, iter_course_blocks
from .hashing import hash_text
from .models import ContentCheck, ContentCheckStatus, CourseReport
from .providers import get_provider

log = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_block_publish(self, usage_key, course_id, block_type, force_recheck=False):
    """
    Core pipeline entry point for a single block.

    Args:
        usage_key: The block's usage key string.
        course_id: The course key string.
        block_type: The block type (html, problem, video).
        force_recheck: If True, skip the hash comparison and always send
                       to the plagiarism provider. Used by nightly_resweep
                       to catch newly-published web sources matching
                       unchanged content.
    """
    log.info(
        "[content_integrity] process_block_publish START: usage_key=%s, block_type=%s, course_id=%s, force_recheck=%s",
        usage_key, block_type, course_id, force_recheck,
    )

    check, created = ContentCheck.objects.get_or_create(
        usage_key=usage_key,
        defaults={"course_id": course_id, "block_type": block_type},
    )
    if created:
        log.info("[content_integrity] Created new ContentCheck record for %s", usage_key)
    else:
        log.debug("[content_integrity] Found existing ContentCheck for %s (status=%s)", usage_key, check.status)

    # In case a block moved course runs or its type metadata changed, keep these in sync.
    if check.course_id != course_id or check.block_type != block_type:
        log.info(
            "[content_integrity] Updating metadata for %s: course_id %s->%s, block_type %s->%s",
            usage_key, check.course_id, course_id, check.block_type, block_type,
        )
        check.course_id, check.block_type = course_id, block_type
        check.save(update_fields=["course_id", "block_type"])

    # --- Step 1: Extract text from the block ---
    try:
        log.debug("[content_integrity] Fetching block content from modulestore for %s", usage_key)
        raw_block = fetch_block_content(usage_key)
        text = extract_plain_text(block_type, raw_block)
        log.info(
            "[content_integrity] Extraction complete for %s: got %d chars of text",
            usage_key, len(text) if text else 0,
        )
    except ValueError as exc:
        log.error("[content_integrity] Extraction failed (bad data) for %s: %s", usage_key, exc)
        check.status = ContentCheckStatus.ERROR
        check.error_message = str(exc)[:2000]
        check.save(update_fields=["status", "error_message", "updated_at"])
        refresh_course_report.delay(course_id)
        return
    except Exception as exc:
        log.exception("[content_integrity] Extraction failed (unexpected error) for %s", usage_key)
        check.status = ContentCheckStatus.ERROR
        check.error_message = str(exc)[:2000]
        check.save(update_fields=["status", "error_message", "updated_at"])
        refresh_course_report.delay(course_id)
        raise self.retry(exc=exc)

    # --- Step 2: Check if text is long enough to scan ---
    text_len = len(text.strip()) if text else 0
    min_length = 10 if block_type in ("problem", "video", "openassessment") else 50
    
    if not text or text_len < min_length:
        log.info(
            "[content_integrity] SKIPPED %s: text too short (%d chars, need %d+)",
            usage_key, text_len, min_length,
        )
        check.status = ContentCheckStatus.SKIPPED
        check.last_checked_at = timezone.now()
        check.error_message = f"Skipped: Content too short for plagiarism scan (needs ~{min_length} chars)"
        check.save(update_fields=["status", "last_checked_at", "updated_at", "error_message"])
        refresh_course_report.delay(course_id)
        return

    # --- Step 3: Hash the text and compare to stored hash ---
    new_hash = hash_text(text)
    log.debug("[content_integrity] Hash for %s: new=%s, stored=%s", usage_key, new_hash[:12], (check.content_hash or "")[:12])

    # Same hash as last time, and we already have a real (non-error,
    # non-pending) result for it -> nothing to do.
    # Unless force_recheck is True (nightly resweep), in which case we
    # always send to the provider to catch newly-published web sources.
    if not force_recheck and new_hash == check.content_hash and check.status in (
        ContentCheckStatus.CLEAN,
        ContentCheckStatus.FLAGGED,
    ):
        log.info(
            "[content_integrity] HASH MATCH for %s — content unchanged and status is %s, skipping Copyleaks call",
            usage_key, check.status,
        )
        check.last_checked_at = timezone.now()
        check.save(update_fields=["last_checked_at", "updated_at"])
        return

    # --- Step 4: Content changed or needs recheck — send to plagiarism provider ---
    log.info(
        "[content_integrity] Content changed or needs check for %s — dispatching run_plagiarism_check (hash: %s -> %s)",
        usage_key, (check.content_hash or "none")[:12], new_hash[:12],
    )
    run_plagiarism_check.delay(
        usage_key=usage_key, course_id=course_id, text=text, content_hash=new_hash,
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def run_plagiarism_check(self, usage_key, course_id, text, content_hash):
    log.info(
        "[content_integrity] run_plagiarism_check START: usage_key=%s, text_length=%d",
        usage_key, len(text),
    )

    try:
        check = ContentCheck.objects.get(usage_key=usage_key)
    except ContentCheck.DoesNotExist:
        log.warning("[content_integrity] ContentCheck for %s vanished before check could run — aborting", usage_key)
        return

    provider = get_provider()
    log.info("[content_integrity] Using provider: %s", provider.name)

    # Determine if we have a public webhook domain configured
    public_domain = getattr(settings, "CONTENT_INTEGRITY_PUBLIC_WEBHOOK_DOMAIN", "")

    try:
        # Pass the public domain to check_text so it can build the webhook URL if available
        result = provider.check_text(text, webhook_url=public_domain)
    except Exception as exc:
        log.error(
            "[content_integrity] Provider check_text failed for %s: %s",
            usage_key, exc,
        )
        check.status = ContentCheckStatus.ERROR
        check.error_message = str(exc)[:2000]
        check.save(update_fields=["status", "error_message", "updated_at"])
        raise self.retry(exc=exc)

    check.content_hash = content_hash
    check.provider = provider.name
    check.scan_id = result.scan_id or ""

    if result.is_pending:
        log.info("[content_integrity] Provider check for %s is PENDING via webhook.", usage_key)
        check.status = ContentCheckStatus.PENDING
        check.save(update_fields=["content_hash", "provider", "scan_id", "status", "updated_at"])
        # Do not refresh_course_report here; wait for webhook
        return

    # If it completed synchronously (e.g. webhook.site fallback or instant mock)
    log.info(
        "[content_integrity] Provider returned SYNCHRONOUS result for %s: score=%.1f, sources=%d",
        usage_key, result.score, len(result.matched_sources),
    )
    threshold = getattr(settings, "CONTENT_INTEGRITY_FLAG_THRESHOLD", 20.0)
    ai_threshold = getattr(settings, "CONTENT_INTEGRITY_AI_FLAG_THRESHOLD", 50.0)

    check.score = result.score
    check.matched_sources = [m.to_dict() for m in result.matched_sources]
    check.ai_score = result.ai_generated_likelihood
    check.grammar_score = result.grammar_score
    check.readability_text = result.readability_text
    
    flag_reasons = []
    if check.score >= threshold:
        flag_reasons.append("plagiarism")
    if check.ai_score is not None and check.ai_score >= ai_threshold:
        flag_reasons.append("ai_generated")
        
    check.flag_reasons = flag_reasons
    check.status = ContentCheckStatus.FLAGGED if flag_reasons else ContentCheckStatus.CLEAN
    check.last_checked_at = timezone.now()
    
    check.save(update_fields=[
        "content_hash", "provider", "scan_id", "score", "matched_sources", 
        "ai_score", "grammar_score", "readability_text", "flag_reasons",
        "status", "last_checked_at", "updated_at"
    ])
    
    refresh_course_report.delay(course_id)


@shared_task
def refresh_course_report(course_id):
    log.debug("[content_integrity] refresh_course_report START for course %s", course_id)
    try:
        checks = ContentCheck.objects.filter(course_id=course_id)
        total = checks.count()
        if total == 0:
            log.debug("[content_integrity] No ContentCheck rows for course %s, skipping report", course_id)
            return

        checked = checks.exclude(status=ContentCheckStatus.PENDING).count()
        flagged_qs = checks.filter(status=ContentCheckStatus.FLAGGED).order_by("-score")
        flagged = flagged_qs.count()

        scored = list(checks.exclude(score__isnull=True).values_list("score", flat=True))
        avg_score = (sum(scored) / len(scored)) if scored else None

        summary = {
            "flagged_blocks": [
                {"usage_key": c.usage_key, "score": c.score, "matched_sources": c.matched_sources}
                for c in flagged_qs[:50]
            ],
        }

        CourseReport.objects.update_or_create(
            course_id=course_id,
            defaults={
                "total_components": total,
                "checked_components": checked,
                "flagged_components": flagged,
                "average_score": avg_score,
                "is_complete": checked == total,
                "summary": summary,
            },
        )
        log.info(
            "[content_integrity] Course report updated for %s: total=%d, checked=%d, flagged=%d, avg_score=%s",
            course_id, total, checked, flagged, f"{avg_score:.1f}" if avg_score is not None else "N/A",
        )
    except Exception as exc:
        log.exception("[content_integrity] Failed to refresh course report for course %s", course_id)


@shared_task
def process_block_deletion(usage_key):
    deleted_count, _ = ContentCheck.objects.filter(usage_key=usage_key).delete()
    if deleted_count:
        log.info("[content_integrity] Deleted ContentCheck for removed block %s", usage_key)
    else:
        log.debug("[content_integrity] No ContentCheck found to delete for %s", usage_key)


@shared_task
def enqueue_children_checks(course_id):
    """
    Called when a container block (vertical/sequential/chapter/course) is
    published. Enumerates all checkable leaf blocks in the course and
    enqueues a process_block_publish task for each one.

    This handles the XBLOCK_PUBLISHED aggregation behavior where a single
    event fires for the parent block rather than individual events for
    each child.
    """
    log.info("[content_integrity] enqueue_children_checks START for course %s", course_id)
    try:
        count = 0
        for block in iter_course_blocks(course_id):
            log.debug(
                "[content_integrity] Enqueuing child block: %s (%s)",
                block["usage_key"], block["block_type"],
            )
            process_block_publish.delay(
                usage_key=block["usage_key"],
                course_id=course_id,
                block_type=block["block_type"],
            )
            count += 1

        log.info(
            "[content_integrity] enqueue_children_checks DONE: enqueued %d block checks for course %s",
            count, course_id,
        )
        # Refresh the course report after all blocks are enqueued.
        # Individual checks will also trigger refreshes as they complete.
        refresh_course_report.delay(course_id)
    except Exception as exc:
        log.exception("[content_integrity] Failed to enqueue children checks for course %s", course_id)


@shared_task
def nightly_resweep(course_id):
    """
    Optional periodic job (wire up via Celery beat) — re-checks *unchanged*
    content too, since a block can go from "clean" to "matches something"
    purely because new sources appeared on the web since the last check.

    Uses force_recheck=True to cleanly bypass the hash short-circuit
    without mutating status in a loop (avoiding race conditions with
    concurrent publish events).
    """
    log.info("[content_integrity] nightly_resweep START for course %s", course_id)
    try:
        count = 0
        for block in iter_course_blocks(course_id):
            process_block_publish.delay(
                usage_key=block["usage_key"],
                course_id=course_id,
                block_type=block["block_type"],
                force_recheck=True,
            )
            count += 1

        log.info("[content_integrity] nightly_resweep DONE: enqueued %d blocks for course %s with force_recheck", count, course_id)
    except Exception as exc:
        log.exception("[content_integrity] Failed nightly resweep for course %s", course_id)
