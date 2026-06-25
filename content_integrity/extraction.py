"""
Pulls course content directly out of the Open edX modulestore.

Because this plugin runs **inside** the CMS (Studio) Django process, we have
direct Python access to the modulestore — the same data layer Studio itself
uses. This is dramatically more reliable than calling the REST API over HTTP,
which requires OAuth tokens, has undocumented parameter requirements, and
returns inconsistent response shapes across Open edX versions.

Block-type support:
  html    — reads the block's ``data`` field (raw HTML) and strips tags.
  video   — reads the ``transcripts`` field and extracts SRT text.
  problem — reads the block's ``data`` field (OLX XML) and extracts text.
"""
import logging
import re
import json

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modulestore helpers — direct Python access, no HTTP
# ---------------------------------------------------------------------------

def _get_modulestore():
    """Import and return the modulestore singleton.  Deferred import so the
    module can be loaded outside of a Django context (e.g. in tests)."""
    from xmodule.modulestore.django import modulestore
    return modulestore()


def _parse_usage_key(usage_key_str: str):
    """Convert a usage-key string into an OpaqueKey object."""
    from opaque_keys.edx.keys import UsageKey
    return UsageKey.from_string(usage_key_str)


def _parse_course_key(course_id_str: str):
    """Convert a course-key string into an OpaqueKey object."""
    from opaque_keys.edx.keys import CourseKey
    return CourseKey.from_string(course_id_str)


# ---------------------------------------------------------------------------
# iter_course_blocks — enumerate all checkable children
# ---------------------------------------------------------------------------

CHECKABLE_TYPES = frozenset({"html", "problem", "video", "openassessment"})


def iter_course_blocks(course_id: str, block_types=("vertical",)):
    """Yield {"usage_key": ..., "block_type": ...} for every checkable block
    in a course, reading directly from the modulestore.

    This replaces the old REST-API-based approach which was fragile and
    prone to 400 errors and inconsistent response formats.
    """
    store = _get_modulestore()
    course_key = _parse_course_key(course_id)
    wanted = frozenset(block_types)

    log.info("[content_integrity] Enumerating blocks for course %s (types: %s)", course_id, wanted)

    try:
        items = store.get_items(course_key, qualifiers={"category": {"$in": list(wanted)}})
    except Exception as exc:
        log.exception("[content_integrity] Failed to enumerate blocks for course %s via modulestore", course_id)
        raise ValueError(f"Failed to enumerate blocks for course {course_id}") from exc

    count = 0
    for item in items:
        count += 1
        yield {
            "usage_key": str(item.location),
            "block_type": item.location.block_type,
        }
    log.info("[content_integrity] Found %d checkable blocks in course %s", count, course_id)


# ---------------------------------------------------------------------------
# fetch_block_content — get a single block's fields from modulestore
# ---------------------------------------------------------------------------

def fetch_block_content(usage_key: str) -> dict:
    """Load a single block from the modulestore and return a dict with the
    fields our extractors need.

    For html blocks:    {"data": "<p>Hello world</p>", "id": "block-v1:..."}
    For video blocks:   {"transcripts": {"en": "..."}, "sub": "...", "id": "block-v1:..."}
    For problem blocks: {"data": "<problem>...</problem>", "id": "block-v1:..."}
    """
    store = _get_modulestore()
    key = _parse_usage_key(usage_key)

    try:
        block = store.get_item(key)
    except Exception as exc:
        log.exception("[content_integrity] Failed to load block %s from modulestore", usage_key)
        raise ValueError(f"Failed to load block {usage_key} from modulestore") from exc

    result = {"id": usage_key}

    # html blocks store their HTML in the ``data`` field.
    if hasattr(block, "data"):
        result["data"] = block.data
        log.debug("[content_integrity] Block %s has 'data' field (%d chars)", usage_key, len(block.data) if block.data else 0)

    # video blocks store transcript info in several fields.
    if hasattr(block, "transcripts"):
        result["transcripts"] = block.transcripts
        log.debug("[content_integrity] Block %s has 'transcripts' field: %s", usage_key, block.transcripts)
    if hasattr(block, "sub"):
        result["sub"] = block.sub
        log.debug("[content_integrity] Block %s has 'sub' field: %s", usage_key, block.sub)
    if hasattr(block, "youtube_id_1_0"):
        result["youtube_id_1_0"] = block.youtube_id_1_0
    if hasattr(block, "edx_video_id"):
        result["edx_video_id"] = block.edx_video_id

    # openassessment blocks store their text in prompt and rubric_criteria
    if hasattr(block, "prompt"):
        result["prompt"] = block.prompt
    if hasattr(block, "rubric_criteria"):
        result["rubric_criteria"] = block.rubric_criteria

    # For vertical blocks, gather their children usage keys and recursively fetch their content.
    if key.block_type == "vertical" and hasattr(block, "children"):
        result["children"] = []
        for child_key in block.children:
            try:
                child_data = fetch_block_content(str(child_key))
                result["children"].append(child_data)
            except Exception as e:
                log.warning("[content_integrity] Failed to fetch child %s for vertical %s: %s", child_key, usage_key, e)

    return result


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------

def _extract_html(block: dict) -> str:
    """Extract plain text from an HTML block's ``data`` field."""
    html = block.get("data", "")
    if not html:
        log.info("[content_integrity] HTML block %s has no 'data' field, returning empty", block.get("id"))
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ")
    log.info("[content_integrity] Extracted %d chars from HTML block %s", len(text.strip()), block.get("id"))
    return text


# ---------------------------------------------------------------------------
# Video transcript extraction
# ---------------------------------------------------------------------------

# SRT timestamp pattern: "00:00:01,000 --> 00:00:05,000"
_SRT_TIMESTAMP_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}$"
)
# Sequence numbers in SRT are just bare integers on a line
_SRT_SEQUENCE_RE = re.compile(r"^\d+$")


def _parse_srt_to_text(srt_content: str) -> str:
    """
    Parse SubRip (.srt) subtitle content and extract just the text lines.
    """
    lines = []
    for line in srt_content.splitlines():
        line = line.strip()
        if not line:
            continue
        if _SRT_SEQUENCE_RE.match(line):
            continue
        if _SRT_TIMESTAMP_RE.match(line):
            continue
        clean = BeautifulSoup(line, "html.parser").get_text()
        if clean.strip():
            lines.append(clean.strip())
    return " ".join(lines)


def _extract_video(block: dict) -> str:
    sub = block.get("sub", "")
    transcripts = block.get("transcripts", {})

    transcript_name = None
    if isinstance(transcripts, dict) and transcripts:
        transcript_name = transcripts.get("en") or next(iter(transcripts.values()), None)
    if not transcript_name and sub:
        transcript_name = sub

    if not transcript_name:
        youtube_id = block.get("youtube_id_1_0")
        if youtube_id:
            return ""
        return ""

    # Parse keys early so we can use the course_key in default_storage paths
    try:
        usage_key = _parse_usage_key(block.get("id", ""))
        course_key = usage_key.course_key
    except Exception:
        usage_key = None
        course_key = None

    # --- FIX 1: Add course_key paths to default_storage check ---
    try:
        from django.core.files.storage import default_storage
        
        storage_paths = [
            transcript_name,
            f"video_transcripts/{transcript_name}",
            f"video-transcripts/{transcript_name}",
            f"edxval/video_transcripts/{transcript_name}" # <-- NEW: EdxVal specific media folder
        ]
        
        # Modern Open edX often nests these inside a course-specific folder
        if course_key:
            storage_paths.extend([
                f"video_transcripts/{course_key}/{transcript_name}",
                f"video-transcripts/{course_key}/{transcript_name}"
            ])
        
        for path in storage_paths:
            if default_storage.exists(path):
                log.info("[content_integrity] Found transcript in default_storage at: %s", path)
                with default_storage.open(path, 'rb') as f:
                    file_content = f.read().decode("utf-8")
                    if path.endswith('.srt'):
                        return _parse_srt_to_text(file_content)
                    return file_content.strip()
    except Exception as e:
        log.warning("[content_integrity] default_storage check failed: %s", e)

    # --- FIX 2: Strip baked-in extensions ---
    clean_name = transcript_name
    for ext in [".srt.sjson", ".sjson", ".srt", ".txt"]:
        if clean_name.endswith(ext):
            clean_name = clean_name[:-len(ext)]
            break

    try:
        from xmodule.contentstore.django import contentstore
        cstore = contentstore()

        extensions = [".srt.sjson", ".srt", ".txt", ""]
        prefixes = ["subs_", ""]
        content = None
        ext_used = None
        
        for ext in extensions:
            for prefix in prefixes:
                try:
                    asset_name = f"{prefix}{clean_name}{ext}"
                    if course_key:
                        asset_key = course_key.make_asset_key("asset", asset_name)
                        content = cstore.find(asset_key)
                        ext_used = ext if ext else ".srt" 
                        break
                except Exception:
                    continue
            if content:
                break
                
        if not content:
            # --- FIX 3: The Hardened VAL Fallback ---
            edx_video_id = block.get("edx_video_id")
            language = "en" # Default fallback
            
            # 1. Extract UUID if missing
            if not edx_video_id:
                match = re.search(r"([a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})", transcript_name)
                if match:
                    edx_video_id = match.group(1)

            # 2. Extract language code from the filename (e.g., "-en.srt" -> "en")
            lang_match = re.search(r"-([a-z]{2,3})\.srt$", transcript_name)
            if lang_match:
                language = lang_match.group(1)

            try:
                from edxval.models import VideoTranscript
                vt = None
                
                # Attempt 1: If the block has a real Video ID, try that first
                if edx_video_id:
                    vt = VideoTranscript.objects.filter(video__edx_video_id=edx_video_id).first()
                
                # Attempt 2: Wildcard search on file-related fields
                if not vt and transcript_name:
                    vt = (
                        VideoTranscript.objects.filter(file__contains=transcript_name).first()
                        or VideoTranscript.objects.filter(file_name__contains=transcript_name).first()
                    )
                if not vt and clean_name:
                    vt = (
                        VideoTranscript.objects.filter(file__contains=clean_name).first()
                        or VideoTranscript.objects.filter(file_name__contains=clean_name).first()
                    )

                if vt:
                    file_content = None
                    
                    # Method 1: Try direct file field access (try multiple possible field names)
                    for field_name in ['file', 'transcript', 'file_data']:
                        f = getattr(vt, field_name, None)
                        if f:
                            try:
                                with f.open('rb') as fh:
                                    file_content = fh.read().decode("utf-8", errors="ignore")
                                break
                            except Exception:
                                try:
                                    file_content = f.read().decode("utf-8", errors="ignore")
                                    break
                                except Exception:
                                    continue
                    
                    # Method 2: Get stored filename and read from default_storage
                    if not file_content:
                        from django.core.files.storage import default_storage as ds
                        fn = getattr(vt, 'file_name', None) or getattr(vt, 'filename', None) or transcript_name
                        for prefix in ['video-transcripts/', 'video_transcripts/', 'edxval/video_transcripts/', '']:
                            path = f"{prefix}{fn}"
                            try:
                                if ds.exists(path):
                                    with ds.open(path, 'rb') as fh:
                                        file_content = fh.read().decode("utf-8", errors="ignore")
                                    log.info("[content_integrity] Found transcript via VAL record + default_storage at: %s", path)
                                    break
                            except Exception:
                                continue
                    
                    if file_content:
                        result = _parse_srt_to_text(file_content)
                        log.info("[content_integrity] Extracted %d chars from VAL transcript for %s", len(result), transcript_name)
                        return result
                
                raise ValueError(f"No transcript asset found for {transcript_name} in contentstore or VAL")
                
            except Exception as val_exc:
                log.warning("[content_integrity] Failed wildcard VAL lookup for %s: %s", transcript_name, val_exc)
            
            raise ValueError(f"No transcript asset found for {transcript_name} in contentstore or VAL")

        if ext_used == ".srt.sjson":
            import json
            sjson = json.loads(content.data.decode("utf-8"))
            texts = sjson.get("text", [])
            result = " ".join(t.strip() for t in texts if t.strip())
        elif ext_used == ".srt":
            result = _parse_srt_to_text(content.data.decode("utf-8"))
        else:
            result = content.data.decode("utf-8").strip()

        return result

    except Exception as exc:
        log.warning(
            "[content_integrity] Could not load transcript for video %s (configured: %s): %s",
            block.get("id"), transcript_name, exc,
        )
        raise ValueError(f"Transcript '{transcript_name}' configured but failed to load: {exc}")

# ---------------------------------------------------------------------------
# Problem block extraction
# ---------------------------------------------------------------------------

def _extract_problem(block: dict) -> str:
    """
    Extract question text from a problem block's OLX (stored in the ``data``
    field directly in the modulestore).
    """
    olx_string = block.get("data", "")
    if not olx_string:
        log.info("[content_integrity] Problem block %s has no 'data' field, returning empty", block.get("id"))
        return ""
    text = _parse_problem_olx(olx_string)
    log.info("[content_integrity] Extracted %d chars from problem block %s", len(text), block.get("id"))
    return text


def _parse_problem_olx(olx_string: str) -> str:
    """
    Parse OLX XML for a problem block and extract visible text.
    """
    # Strip CDATA blocks entirely to prevent python code bleeding through.
    olx_string = re.sub(r"<!\[CDATA\[.*?\]\]>", "", olx_string, flags=re.DOTALL)
    
    try:
        soup = BeautifulSoup(olx_string, "html.parser")
    except Exception as exc:
        log.exception("[content_integrity] Failed to parse OLX XML")
        raise ValueError(f"Failed to parse OLX XML: {exc}") from exc

    # Remove programmatic logic, hints, and styles that aren't the authored prompt.
    # Also remove choice/option tags so we don't extract raw choices like "A B C".
    tags_to_remove = [
        "script", "style", "responseparam", "demandhint", "solution", "customresponse",
        "choice", "option"
    ]
    for tag in soup.find_all(tags_to_remove):
        tag.decompose()

    # Get all text content.
    text = soup.get_text(separator=" ")

    # Clean up whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Open Assessment extraction
# ---------------------------------------------------------------------------

def _extract_openassessment(block: dict) -> str:
    """
    Extract text from an openassessment block.
    ORA blocks typically store their text in `prompt` and `rubric_criteria` fields,
    but may also serialize to XML in the `data` field in older versions.
    """
    parts = []

    # 1. Try to extract from native fields
    prompt = block.get("prompt")
    if prompt:
        try:
            # The prompt might be an HTML string
            prompt_text = BeautifulSoup(str(prompt), "html.parser").get_text(separator=" ").strip()
            if prompt_text:
                parts.append(prompt_text)
        except Exception:
            parts.append(str(prompt).strip())

    rubric_criteria = block.get("rubric_criteria")
    if isinstance(rubric_criteria, list):
        for criterion in rubric_criteria:
            if isinstance(criterion, dict):
                c_prompt = criterion.get("prompt", "")
                if c_prompt:
                    try:
                        c_text = BeautifulSoup(str(c_prompt), "html.parser").get_text(separator=" ").strip()
                        if c_text:
                            parts.append(c_text)
                    except Exception:
                        pass
                c_name = criterion.get("name", "")
                if c_name:
                    parts.append(str(c_name))

    # 2. Fallback to parsing XML in the `data` field
    if not parts:
        olx_string = block.get("data", "")
        if olx_string:
            try:
                soup = BeautifulSoup(olx_string, "html.parser")
                # Extract Prompt
                for prompt_tag in soup.find_all("prompt"):
                    parts.append(prompt_tag.get_text(separator=" ").strip())
                    
                # Extract Rubric descriptions
                for tag in soup.find_all(["criterion", "option"]):
                    name = tag.get("name", "")
                    if name:
                        parts.append(name)
                    text = tag.get_text(separator=" ").strip()
                    if text:
                        parts.append(text)
                        
                # Fallback: if no specific tags found, just get the text of the whole thing
                if not parts:
                    parts.append(soup.get_text(separator=" ").strip())
            except Exception as exc:
                log.exception("[content_integrity] Failed to parse ORA XML")

    text = " ".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    log.info("[content_integrity] Extracted %d chars from ORA block %s", len(text), block.get("id"))
    return text


# ---------------------------------------------------------------------------
# Extractor registry
# ---------------------------------------------------------------------------

_EXTRACTORS = {
    "html": _extract_html,
    "problem": _extract_problem,
    "video": _extract_video,
    "openassessment": _extract_openassessment,
}

# ---------------------------------------------------------------------------
# Vertical block extraction
# ---------------------------------------------------------------------------

def _extract_vertical(block: dict) -> str:
    """
    Extract text from a vertical block by recursively extracting text from all its children
    and concatenating them with clear descriptive headers.
    """
    parts = []
    children = block.get("children", [])
    
    for child in children:
        child_id = child.get("id")
        if not child_id:
            continue
            
        try:
            # Re-parse usage key to find block type
            from opaque_keys.edx.keys import UsageKey
            child_key = UsageKey.from_string(child_id)
            block_type = child_key.block_type
            
            # Extract plain text for the child
            child_text = extract_plain_text(block_type, child)
            if child_text and child_text.strip():
                # Add a descriptive header
                header = f"\n\n--- [{block_type.upper()} Component] ---\n\n"
                parts.append(header + child_text.strip())
        except Exception as e:
            log.warning("[content_integrity] Failed to extract text for child %s: %s", child_id, e)
            
    return "".join(parts).strip()

_EXTRACTORS["vertical"] = _extract_vertical


def extract_plain_text(block_type: str, block: dict) -> str:
    extractor = _EXTRACTORS.get(block_type)
    if not extractor:
        log.info("[content_integrity] No extractor registered for block_type=%s, skipping", block_type)
        return ""
    return extractor(block)
