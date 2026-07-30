"""
Smart Message Parser — Milestone 8
====================================
Classifies free-form Discord thread messages into structured task intents.

Design Principles:
- Pure function: no I/O, no side effects, fully deterministic.
- Rule-based regex scoring: fast, zero-latency, no external dependencies.
- Returns a typed ParsedIntent dataclass consumed by the thread listener.
- Priority ordering: more specific intents rank above generic ones.
- Every pattern is documented with the example phrases it covers.

Intent Priority (highest → lowest):
  COMPLETE > BLOCKED > PROGRESS_UPDATE > START > DEADLINE_EXTENSION
  > NEED_HELP > FILE_UPLOAD > LINK_SHARED > UNRECOGNIZED
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Final


# ─────────────────────────────────────────────────
# Intent Enumeration
# ─────────────────────────────────────────────────

class Intent(str, Enum):
    """All possible classified message intents."""
    COMPLETE          = "COMPLETE"            # Task is done / finished
    BLOCKED           = "BLOCKED"             # Task is blocked / stuck
    START             = "START"               # Starting work now
    PROGRESS_UPDATE   = "PROGRESS_UPDATE"     # General work-in-progress update
    DEADLINE_EXTENSION = "DEADLINE_EXTENSION" # Requesting more time
    NEED_HELP         = "NEED_HELP"           # Asking for help / review
    FILE_UPLOAD       = "FILE_UPLOAD"         # File attachment detected
    LINK_SHARED       = "LINK_SHARED"         # External link detected
    UNRECOGNIZED      = "UNRECOGNIZED"        # Could not classify


# ─────────────────────────────────────────────────
# Supported Link Types
# ─────────────────────────────────────────────────

class LinkType(str, Enum):
    """Classifies the type of external link shared in a message."""
    GOOGLE_DRIVE  = "GOOGLE_DRIVE"
    GITHUB        = "GITHUB"
    GITLAB        = "GITLAB"
    FIGMA         = "FIGMA"
    CANVA         = "CANVA"
    GOOGLE_DOCS   = "GOOGLE_DOCS"
    GOOGLE_SHEETS = "GOOGLE_SHEETS"
    GOOGLE_SLIDES = "GOOGLE_SLIDES"
    NOTION        = "NOTION"
    YOUTUBE       = "YOUTUBE"
    DROPBOX       = "DROPBOX"
    ONEDRIVE      = "ONEDRIVE"
    UNKNOWN       = "UNKNOWN"


# ─────────────────────────────────────────────────
# Supported File Types
# ─────────────────────────────────────────────────

# Engineering-relevant file extensions the platform tracks
SUPPORTED_FILE_EXTENSIONS: Final[frozenset[str]] = frozenset({
    # Images
    "png", "jpg", "jpeg", "gif", "webp", "svg",
    # Documents
    "pdf", "docx", "doc", "pptx", "ppt", "xlsx", "xls", "csv", "txt",
    # Archives
    "zip", "rar", "7z", "tar", "gz",
    # CAD / Engineering
    "step", "stp", "sldprt", "sldasm", "slddrw",
    "dxf", "dwg", "igs", "iges", "stl", "obj",
    # Code / Data
    "py", "js", "ts", "json", "yaml", "yml",
})


# ─────────────────────────────────────────────────
# Result Dataclasses
# ─────────────────────────────────────────────────

@dataclass(frozen=True)
class DetectedLink:
    """A single external link found in a message."""
    url: str
    link_type: LinkType


@dataclass(frozen=True)
class DetectedFile:
    """A file attachment reference found in a message."""
    filename: str
    extension: str


@dataclass
class ParsedIntent:
    """
    The full result of parsing a Discord message.

    Attributes:
        intent:             The primary classified action intent.
        confidence:         Score 0.0–1.0 indicating match strength.
        extracted_text:     The cleaned message text after stripping links/mentions.
        blocked_reason:     Populated when intent is BLOCKED.
        progress_note:      Populated when intent is PROGRESS_UPDATE.
        extension_request:  Populated when intent is DEADLINE_EXTENSION.
        links:              All external links detected in the message.
        files:              All file attachments referenced in the message.
        raw_message:        Original unmodified message content.
    """
    intent: Intent
    confidence: float
    extracted_text: str
    raw_message: str
    blocked_reason: str | None = None
    progress_note: str | None = None
    extension_request: str | None = None
    links: list[DetectedLink] = field(default_factory=list)
    files: list[DetectedFile] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        """True when the intent requires a bot response or state change."""
        return self.intent not in (Intent.UNRECOGNIZED,)

    @property
    def drive_links(self) -> list[str]:
        return [lnk.url for lnk in self.links if lnk.link_type == LinkType.GOOGLE_DRIVE]

    @property
    def github_links(self) -> list[str]:
        return [lnk.url for lnk in self.links if lnk.link_type == LinkType.GITHUB]

    @property
    def all_link_urls(self) -> list[str]:
        return [lnk.url for lnk in self.links]


# ─────────────────────────────────────────────────
# Intent Pattern Definitions
# ─────────────────────────────────────────────────
# Each entry: (pattern, score_weight)
# Multiple patterns can match; scores are summed and capped at 1.0.

_COMPLETE_PATTERNS: Final[list[tuple[str, float]]] = [
    # Strong direct signals
    (r"\b(done|completed?|finished?|complete)\b",           0.7),
    (r"\b(wrapped\s+up|all\s+done|it['']?s\s+done)\b",     0.6),
    (r"\b(submitted|delivered|closed|marked\s+done)\b",     0.5),
    (r"\b(task\s+(is\s+)?(done|complete|finished))\b",      0.8),
    # Causal completion signals
    (r"\b(everything\s+(is\s+)?working|all\s+tests\s+pass)", 0.5),
    (r"\b(pushed\s+to\s+(main|master|prod))\b",             0.4),
    # Exclude partial-done phrases — these are progress, not completion
    # (handled via negative scoring in progress section)
]

# Phrases that look like completion but are actually progress updates.
# Used to DOWN-SCORE completion when these appear alongside "done"/"complete".
_PARTIAL_COMPLETION_PATTERNS: Final[list[tuple[str, float]]] = [
    (r"\b(halfway|partially|about\s+\d+%|\d+%\s+(done|complete)|almost|nearly)\b", 0.5),
    (r"\b(should\s+finish|will\s+finish|finishing\s+(tomorrow|soon|today))\b",      0.4),
]

_BLOCKED_PATTERNS: Final[list[tuple[str, float]]] = [
    # "stuck" alone or "stuck waiting/on hold" = blocked, but NOT "stuck on X" (that's need_help)
    (r"\b(blocked?)\b",                                                          0.7),
    (r"\b(stuck\s+(waiting|on\s+hold|without|because|due))\b",                  0.7),
    (r"\b(waiting\s+for\s+\w+)\b",                                              0.6),
    (r"\b(on\s+hold|paused|halted|stopped)\b",                                  0.5),
    (r"\b(need\s+(approval|sign[- ]?off|review|permission))\b",                 0.6),
    (r"\b(blocked\s+(by|on|due\s+to))\b",                                       0.8),
    (r"\b(can[''t]*\s+proceed|cannot\s+proceed)\b",                             0.6),
    (r"\b(can[''t]*\s+continue|unable\s+to\s+(proceed|continue))\b",           0.6),
    (r"\b(manufacturing|material|parts?|components?)\s+(not\s+)?(ready|available|arrived)", 0.5),
    (r"\b(waiting\s+for\s+(parts?|delivery|material|vendor))\b",                0.6),
]

_START_PATTERNS: Final[list[tuple[str, float]]] = [
    (r"\b(start(ing|ed)?|begin(ning)?|kicking\s+off|initiating)\b",     0.7),
    (r"\b(on\s+it\s+now|working\s+on\s+it|picking\s+this\s+up)\b",     0.6),
    (r"\b(just\s+start(ed|ing)|started\s+working)\b",                   0.8),
    (r"\b(taking\s+this|assigned\s+myself|on\s+my\s+plate)\b",          0.5),
    (r"\b(will\s+start\s+(now|today|shortly))\b",                       0.6),
]

_PROGRESS_PATTERNS: Final[list[tuple[str, float]]] = [
    (r"\b(working\s+on|still\s+working|in\s+progress|ongoing)\b",       0.6),
    # Explicit update/status prefix is a very strong progress signal
    (r"^(update[:\-\s]+|progress[:\-\s]+|status[:\-\s]+|note[:\-\s]+)", 0.8),
    (r"\b(update[:\-\s]|progress[:\-\s]|status[:\-\s])\b",              0.5),
    (r"\b(partially\s+done|halfway|50%)\b",                              0.6),
    (r"\b(\d+%\s+(done|complete|finished))\b",                           0.6),
    (r"\b(made\s+progress|some\s+progress|good\s+progress)\b",           0.6),
    (r"\b(uploaded|attached|added|pushed|committed|deployed)\b",         0.4),
    (r"\b(ran\s+tests?|tested|verified|checked|reviewed)\b",             0.4),
    (r"\b(CAD\s+(done|updated|ready)|simulation\s+(ran|complete))\b",   0.5),
]

_DEADLINE_EXTENSION_PATTERNS: Final[list[tuple[str, float]]] = [
    (r"\b(need\s+(more|extra|another)\s+(day|days|hour|hours|week|time))\b",    0.8),
    (r"\b(extend(ing)?\s+(the\s+)?deadline|deadline\s+extension)\b",            0.9),
    (r"\b(can\s+(you|we)\s+push\s+(the\s+)?deadline)\b",                        0.8),
    (r"\b(push\s+(the\s+)?deadline)\b",                                          0.8),
    (r"\b(requesting\s+(more\s+)?time|time\s+extension)\b",                     0.7),
    (r"\b(will\s+(take|need)\s+(one|1|two|2|a\s+few)\s+(more\s+)?(day|days))\b", 0.7),
    (r"\b(behind\s+schedule|running\s+late|delayed)\b",                          0.5),
    (r"\b(not\s+finishing\s+(today|on\s+time|by\s+deadline))\b",                0.6),
    # "need 2 more days" / "need another 3 days"
    (r"\b(need\s+\d+\s+more\s+(day|days|hour|hours))\b",                        0.8),
    # "taking longer than expected"
    (r"\b(taking\s+longer\s+than\s+(expected|planned|anticipated))\b",          0.6),
]

_NEED_HELP_PATTERNS: Final[list[tuple[str, float]]] = [
    (r"\b(need\s+help|help\s+(me|needed|required|please))\b",           0.7),
    (r"\b(can\s+(someone|anyone)\s+(help|assist|review))\b",            0.7),
    (r"\b(question[:\-\s]|doubt[:\-\s]|confused\s+about)\b",           0.5),
    (r"\b(how\s+do\s+I|how\s+to|not\s+sure\s+how)\b",                  0.5),
    (r"\b(please\s+review|review\s+(this|my|the))\b",                   0.6),
    # "stuck on X" (without blocked context) = need help
    (r"\b(stuck\s+on\s+\w+)\b",                                         0.5),
    (r"\b(trouble\s+with|issue\s+with|problem\s+with)\b",               0.5),
]


# ─────────────────────────────────────────────────
# Link Detection Patterns
# ─────────────────────────────────────────────────

_LINK_PATTERNS: Final[list[tuple[re.Pattern[str], LinkType]]] = [
    (re.compile(r"https?://(?:docs\.google\.com/spreadsheets|sheets\.google\.com)\S+",  re.I), LinkType.GOOGLE_SHEETS),
    (re.compile(r"https?://(?:docs\.google\.com/presentation)\S+",                      re.I), LinkType.GOOGLE_SLIDES),
    (re.compile(r"https?://(?:docs\.google\.com/document)\S+",                          re.I), LinkType.GOOGLE_DOCS),
    (re.compile(r"https?://(?:drive\.google\.com|docs\.google\.com)\S+",               re.I), LinkType.GOOGLE_DRIVE),
    (re.compile(r"https?://(?:www\.)?github\.com\S+",                                   re.I), LinkType.GITHUB),
    (re.compile(r"https?://(?:www\.)?gitlab\.com\S+",                                   re.I), LinkType.GITLAB),
    (re.compile(r"https?://(?:www\.)?figma\.com\S+",                                    re.I), LinkType.FIGMA),
    (re.compile(r"https?://(?:www\.)?canva\.com\S+",                                    re.I), LinkType.CANVA),
    (re.compile(r"https?://(?:www\.)?notion\.so\S+",                                    re.I), LinkType.NOTION),
    (re.compile(r"https?://(?:www\.)?youtube\.com\S+|https?://youtu\.be\S+",            re.I), LinkType.YOUTUBE),
    (re.compile(r"https?://(?:www\.)?dropbox\.com\S+",                                  re.I), LinkType.DROPBOX),
    (re.compile(r"https?://(?:onedrive\.live\.com|1drv\.ms)\S+",                        re.I), LinkType.ONEDRIVE),
]

# Catch-all URL pattern for unclassified links
_URL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"https?://[^\s<>\"']+",
    re.I
)


# ─────────────────────────────────────────────────
# File Mention Patterns
# ─────────────────────────────────────────────────

# Matches filenames like "rear_wing.step", "cfd_results.pdf", "telemetry.csv"
# Uses a lookbehind for non-word or start-of-string so "check rear_wing.step"
# captures only "rear_wing.step", not "check rear_wing.step".
_FILENAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:^|(?<=\s)|(?<=[,(\"'`]))(\w[\w\-]*\.("
    + "|".join(re.escape(ext) for ext in sorted(SUPPORTED_FILE_EXTENSIONS, key=len, reverse=True))
    + r"))(?=\s|$|[,)\"'`])",
    re.I | re.MULTILINE
)

# Matches upload mentions like "uploaded CAD", "attached report", "shared PDF"
_UPLOAD_MENTION_PATTERNS: Final[list[str]] = [
    r"\b(uploaded?|attached|shared|sent|added)\s+([\w\s\-.]+\.(pdf|step|stp|dxf|zip|rar|docx|xlsx|csv|png|jpg|jpeg))\b",
    r"\b(uploaded?|attached|shared)\s+(cad|model|drawing|report|simulation|results?|photos?|images?|files?)\b",
    r"\b(here[''']?s?\s+(the|my|a)?\s*)(cad|model|drawing|report|pdf|simulation|file|image|photo)\b",
]


# ─────────────────────────────────────────────────
# Core Scoring Engine
# ─────────────────────────────────────────────────

def _score_intent(text: str, patterns: list[tuple[str, float]]) -> float:
    """
    Scores a text against a list of (pattern, weight) pairs.
    Returns cumulative score capped at 1.0.
    """
    score = 0.0
    text_lower = text.lower()
    for pattern, weight in patterns:
        if re.search(pattern, text_lower, re.I):
            score += weight
    return min(score, 1.0)


def _detect_links(text: str) -> list[DetectedLink]:
    """
    Extracts all URLs from the message and classifies each by link type.
    Specific patterns are checked first; falls back to UNKNOWN for unmatched URLs.
    """
    found_urls: set[str] = set()
    results: list[DetectedLink] = []

    # Check specific patterns first (ordered most-specific to least)
    for pattern, link_type in _LINK_PATTERNS:
        for match in pattern.finditer(text):
            url = match.group(0).rstrip(".,;:)")
            if url not in found_urls:
                found_urls.add(url)
                results.append(DetectedLink(url=url, link_type=link_type))

    # Catch remaining URLs not matched by specific patterns
    for match in _URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(".,;:)")
        if url not in found_urls:
            found_urls.add(url)
            results.append(DetectedLink(url=url, link_type=LinkType.UNKNOWN))

    return results


def _detect_files(text: str, attachment_filenames: list[str] | None = None) -> list[DetectedFile]:
    """
    Detects file references in message text and from actual Discord attachments.

    Args:
        text:                 The message content.
        attachment_filenames: Actual filenames from Discord attachment objects.
    """
    results: list[DetectedFile] = []
    seen: set[str] = set()

    # 1. Actual Discord attachment filenames (most reliable)
    if attachment_filenames:
        for filename in attachment_filenames:
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext in SUPPORTED_FILE_EXTENSIONS and filename not in seen:
                seen.add(filename)
                results.append(DetectedFile(filename=filename, extension=ext))

    # 2. Filenames mentioned in text (e.g. "see rear_wing.step")
    for match in _FILENAME_PATTERN.finditer(text):
        filename = match.group(1)
        ext = match.group(2).lower()
        if filename not in seen:
            seen.add(filename)
            results.append(DetectedFile(filename=filename, extension=ext))

    return results


def _extract_blocked_reason(text: str) -> str | None:
    """
    Attempts to extract the specific reason for being blocked from the message.
    Returns the full sentence if a block-related keyword is found.
    """
    sentences = re.split(r"[.!?]", text)
    block_keywords = re.compile(
        r"\b(blocked?|stuck|waiting|on\s+hold|need\s+(approval|review|permission)|can[''t]*\s+proceed)\b",
        re.I
    )
    for sentence in sentences:
        if block_keywords.search(sentence):
            cleaned = sentence.strip()
            if cleaned:
                return cleaned
    return text.strip() if text.strip() else None


def _extract_progress_note(text: str) -> str | None:
    """Extracts the update text for a progress message, stripping boilerplate."""
    # Strip common boilerplate prefixes
    cleaned = re.sub(
        r"^(update[:\-\s]+|progress[:\-\s]+|status[:\-\s]+|note[:\-\s]+)",
        "",
        text.strip(),
        flags=re.I
    ).strip()
    return cleaned if cleaned else text.strip()


def _extract_extension_request(text: str) -> str | None:
    """Extracts the extension request detail (e.g. 'need 2 more days')."""
    pattern = re.compile(
        r"(need\s+(?:more|extra|another)?\s*(?:\d+\s+)?(?:day|days|hour|hours|week|weeks?|more\s+time)[^.!?]*)",
        re.I
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


# ─────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────

def parse_message(
    content: str,
    attachment_filenames: list[str] | None = None
) -> ParsedIntent:
    """
    Parse a Discord message into a structured intent.

    This is the primary entry point for the smart message parser.
    It is a pure function — stateless, deterministic, side-effect-free.

    Args:
        content:              Raw Discord message content string.
        attachment_filenames: List of filenames from Discord Message.attachments.
                              Pass this to correctly detect file uploads.

    Returns:
        ParsedIntent with classified intent, confidence score,
        extracted metadata, detected links, and detected files.

    Examples:
        >>> parse_message("done, pushed to main")
        ParsedIntent(intent=Intent.COMPLETE, confidence=0.7, ...)

        >>> parse_message("blocked waiting for manufacturing parts")
        ParsedIntent(intent=Intent.BLOCKED, blocked_reason="blocked waiting for manufacturing parts", ...)

        >>> parse_message("starting on this now")
        ParsedIntent(intent=Intent.START, confidence=0.7, ...)

        >>> parse_message("need 2 more days please")
        ParsedIntent(intent=Intent.DEADLINE_EXTENSION, ...)
    """
    if not content or not content.strip():
        return ParsedIntent(
            intent=Intent.UNRECOGNIZED,
            confidence=0.0,
            extracted_text="",
            raw_message=content or "",
        )

    raw = content
    text = content.strip()

    # ── Step 1: Detect links and files ──────────────────────────────
    links = _detect_links(text)
    files = _detect_files(text, attachment_filenames)

    # ── Step 2: Score all intents ────────────────────────────────────
    scores: dict[Intent, float] = {
        Intent.COMPLETE:           _score_intent(text, _COMPLETE_PATTERNS),
        Intent.BLOCKED:            _score_intent(text, _BLOCKED_PATTERNS),
        Intent.START:              _score_intent(text, _START_PATTERNS),
        Intent.PROGRESS_UPDATE:    _score_intent(text, _PROGRESS_PATTERNS),
        Intent.DEADLINE_EXTENSION: _score_intent(text, _DEADLINE_EXTENSION_PATTERNS),
        Intent.NEED_HELP:          _score_intent(text, _NEED_HELP_PATTERNS),
    }

    # ── Step 2b: Penalise COMPLETE when partial-completion signals are present ──
    # "halfway done", "about 70% done" → PROGRESS, not COMPLETE
    partial_score = _score_intent(text, _PARTIAL_COMPLETION_PATTERNS)
    if partial_score >= 0.4:
        scores[Intent.COMPLETE] = max(0.0, scores[Intent.COMPLETE] - partial_score)
        scores[Intent.PROGRESS_UPDATE] = min(1.0, scores[Intent.PROGRESS_UPDATE] + 0.4)

    # ── Step 3: File upload signals ──────────────────────────────────
    # Actual attachment or upload mention = strong FILE_UPLOAD signal
    file_upload_score = 0.0
    if attachment_filenames:
        file_upload_score = 0.95  # Actual Discord attachment = very high confidence
    else:
        for pattern in _UPLOAD_MENTION_PATTERNS:
            if re.search(pattern, text, re.I):
                file_upload_score = max(file_upload_score, 0.7)
    scores[Intent.FILE_UPLOAD] = file_upload_score

    # ── Step 4: Link shared signal ───────────────────────────────────
    # If links were found and no other strong intent scored higher
    link_score = 0.5 if links else 0.0
    scores[Intent.LINK_SHARED] = link_score

    # ── Step 5: Apply priority ordering ──────────────────────────────
    # Priority ordering with FILE_UPLOAD elevated when actual attachments present.
    # If real attachments exist, FILE_UPLOAD beats everything except BLOCKED.
    # This ensures "done, attaching report" with actual file → FILE_UPLOAD primary,
    # but "done" with no attachment → COMPLETE primary.
    PRIORITY_ORDER: list[Intent]
    if attachment_filenames:
        PRIORITY_ORDER = [
            Intent.BLOCKED,
            Intent.FILE_UPLOAD,
            Intent.COMPLETE,
            Intent.DEADLINE_EXTENSION,
            Intent.START,
            Intent.PROGRESS_UPDATE,
            Intent.NEED_HELP,
            Intent.LINK_SHARED,
        ]
    else:
        PRIORITY_ORDER = [
            Intent.COMPLETE,
            Intent.BLOCKED,
            Intent.DEADLINE_EXTENSION,
            Intent.START,
            Intent.PROGRESS_UPDATE,
            Intent.NEED_HELP,
            Intent.FILE_UPLOAD,
            Intent.LINK_SHARED,
        ]

    CONFIDENCE_THRESHOLD = 0.4  # Minimum score to be considered actionable

    best_intent = Intent.UNRECOGNIZED
    best_score = 0.0

    for intent in PRIORITY_ORDER:
        score = scores.get(intent, 0.0)
        if score >= CONFIDENCE_THRESHOLD and score > best_score:
            best_intent = intent
            best_score = score

    # ── Step 6: Upgrade LINK_SHARED / FILE_UPLOAD if links/files exist ──
    # If no other strong intent was found but links/files are present,
    # those are the primary signal.
    if best_intent == Intent.UNRECOGNIZED:
        if files:
            best_intent = Intent.FILE_UPLOAD
            best_score = 0.9 if attachment_filenames else 0.7
        elif links:
            best_intent = Intent.LINK_SHARED
            best_score = 0.5

    # ── Step 7: Strip URLs from extracted_text ───────────────────────
    extracted = _URL_PATTERN.sub("", text).strip()
    extracted = re.sub(r"\s{2,}", " ", extracted)

    # ── Step 8: Extract intent-specific metadata ─────────────────────
    blocked_reason: str | None = None
    progress_note: str | None = None
    extension_request: str | None = None

    if best_intent == Intent.BLOCKED:
        blocked_reason = _extract_blocked_reason(extracted or text)

    elif best_intent == Intent.PROGRESS_UPDATE:
        progress_note = _extract_progress_note(extracted or text)

    elif best_intent == Intent.DEADLINE_EXTENSION:
        extension_request = _extract_extension_request(extracted or text)

    return ParsedIntent(
        intent=best_intent,
        confidence=round(best_score, 3),
        extracted_text=extracted,
        raw_message=raw,
        blocked_reason=blocked_reason,
        progress_note=progress_note,
        extension_request=extension_request,
        links=links,
        files=files,
    )
