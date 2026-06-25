# openedx-content-integrity

Async plagiarism / AI-authenticity reporting for Open edX course content.
Non-blocking — never prevents publishing, only generates a report.

## What it does

1. Listens for `XBLOCK_PUBLISHED` whenever a course author publishes content in Studio.
   - **Container blocks** (vertical, sequential, chapter, course): automatically
     enumerates all checkable children via the Course Blocks API.
   - **Leaf blocks** (html, problem, video): queued directly for checking.
2. Pulls each block's content via the Course Blocks API and extracts plain text:
   - **HTML blocks**: strips tags via BeautifulSoup.
   - **Video blocks**: downloads SRT transcript from the URL in `student_view_data.transcripts`,
     parses it into plain text.
   - **Problem blocks**: calls the OLX export REST API
     (`/api/olx-export/v1/xblock/{usage_key}/`) to get the raw XML, then
     extracts question stems, answer options, hints, and solutions.
3. Hashes the text and compares it to the hash from the last successful check.
   Unchanged content is skipped entirely — only actually-changed blocks get
   sent to the plagiarism provider.
4. Stores per-block results (`ContentCheck`) and rolls them up into a
   per-course summary (`CourseReport`).
5. Exposes both over a small REST API, restricted to course staff/instructors.

## Install (Tutor)

```bash
pip install -e /path/to/openedx-content-integrity
```

Add it as a Tutor plugin requirement (or bake it into your CMS/LMS image),
then:

```bash
tutor local run cms ./manage.py cms migrate content_integrity
tutor local restart cms cms-worker lms lms-worker
```

## Install (native devstack / non-Tutor)

```bash
pip install -e .
./manage.py cms migrate content_integrity
```

Make sure `content_integrity` is on the `INSTALLED_APPS` path your plugin
loader picks up (it will be automatic if your edx-platform version
supports the `cms.djangoapp` entry-point plugin pattern, which all
currently-supported releases do).

## Dependencies

### Required (provided by Open edX platform)
- `openedx-events` — for `XBLOCK_PUBLISHED` and `XBLOCK_DELETED` signals.
- `celery` — for async task processing.
- `djangorestframework` — for the report API.
- `opaque-keys` — for `CourseKey` / `UsageKey` parsing.

### Required (installed by this plugin)
- `requests` — HTTP client for API calls.
- `beautifulsoup4` — HTML/XML parsing.
- `lxml` — XML parsing for OLX problem blocks.

### Optional (for problem block checking)
- **`openedx-olx-rest-api`** — this plugin exposes the
  `/api/olx-export/v1/xblock/{usage_key}/` endpoint that we use to get
  raw OLX for problem blocks. If this is **not installed** on your CMS
  instance, problem blocks will be gracefully skipped (marked `SKIPPED`)
  instead of checked. Install it with:
  ```bash
  pip install openedx-olx-rest-api
  ```

## Configure

Set in your CMS env config (`cms.yml` under Tutor, or `AUTH_TOKENS`/`ENV_TOKENS`
for native installs):

| Setting | Purpose |
|---|---|
| `CONTENT_INTEGRITY_PROVIDER` | `"plagiarismcheck"` or `"copyleaks"` |
| `CONTENT_INTEGRITY_FLAG_THRESHOLD` | similarity % at which a block is marked FLAGGED (default 20.0) |
| `CONTENT_INTEGRITY_PLAGIARISMCHECK_API_TOKEN` | from plagiarismcheck.org |
| `CONTENT_INTEGRITY_COPYLEAKS_EMAIL` / `_COPYLEAKS_API_KEY` | from Copyleaks |
| `CMS_ROOT_URL` | Studio CMS URL (needed for OLX export API). In Tutor this is typically `http://cms:8000` internally. |

This also assumes `BACKEND_SERVICE_EDX_OAUTH2_KEY`/`_SECRET` are already
configured on your instance (they almost certainly are — every other IDA
like ecommerce/credentials uses this same client-credentials pattern to
talk to the LMS).

## How `XBLOCK_PUBLISHED` aggregation works

A critical detail: when a course author publishes a section/unit in Studio,
Open edX fires a **single `XBLOCK_PUBLISHED` event** for the parent block
(e.g., the `vertical` or `sequential`), **not** individual events for each
child `html`/`problem`/`video` block.

This plugin handles this correctly:
- When the receiver sees a container block type (vertical, sequential,
  chapter, course), it enqueues a Celery task that calls the Course Blocks
  API to enumerate all checkable children, then enqueues a check for each one.
- When the receiver sees a leaf block type (html, problem, video), it
  enqueues a single check directly.

## Backfilling existing courses

The signal only fires going forward. To run an initial check across a
course you already have:

```bash
./manage.py cms check_course_content course-v1:OrgX+Course+Run
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/content-integrity/v1/courses/<course_id>/report/` | GET | Course-level summary report |
| `/api/content-integrity/v1/courses/<course_id>/blocks/` | GET | Per-block breakdown, ordered by score |

Both endpoints require authentication and course staff/instructor role.

## Optional: nightly resweep

`tasks.nightly_resweep(course_id)` re-checks content even if it hasn't
changed, to catch sources that got published to the web *after* your last
check. It uses the `force_recheck=True` flag to cleanly bypass the hash
short-circuit without race conditions.

Wire it into Celery beat against whichever courses you want on a
recurring schedule — it's not run automatically by anything in this package.

Example Celery beat config:
```python
CELERY_BEAT_SCHEDULE = {
    "content-integrity-weekly-resweep": {
        "task": "content_integrity.tasks.nightly_resweep",
        "schedule": crontab(day_of_week="sunday", hour=2, minute=0),
        "args": ["course-v1:OrgX+Course+Run"],
    },
}
```

## Running tests

```bash
python -m pytest content_integrity/tests/ -v
```

## Things that are real and tested vs. things you need to confirm

**Solid, unit-tested in this package:**
- `hashing.py` — the change-detection logic.
- `extraction._extract_html` — HTML-to-plain-text.
- `extraction._extract_video` — SRT transcript download and parsing.
- `extraction._parse_problem_olx` — OLX XML text extraction.
- `receivers.py` — container vs. leaf block routing.
- The provider abstraction (`providers/base.py`, `providers/__init__.py`)
  and the overall task pipeline shape.

**Confirm against your environment before go-live:**
- `receivers.py` — confirm the exact field names on `XBlockData`
  (`openedx_events.content_authoring.data`) for your installed
  `openedx-events` version.
- `providers/plagiarismcheck.py` and `providers/copyleaks.py` — confirm
  current endpoint paths/JSON shape against the vendors' live docs
  (https://plagiarismcheck.org/for-developers/ and https://docs.copyleaks.com/).
  The submit → poll → parse structure is right; exact field names may have moved.
