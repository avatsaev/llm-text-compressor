"""Core compression logic."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Generator, Iterable


@dataclasses.dataclass(frozen=True, slots=True)
class PreservedSpan:
    """A span of text that was preserved intact during compression."""

    start: int         # position in the COMPRESSED output
    end: int           # position in the COMPRESSED output
    text: str          # the preserved content
    kind: str          # kind: "url", "email", "phone", "uuid", "hex_id", "alphanum_id",
                       # "proper_noun", "acronym", "compressor_off", "fenced_code",
                       # "inline_code", "json", "xml", "preserve"


@dataclasses.dataclass(frozen=True, slots=True)
class CompressionResult:
    """Result of compression with detailed statistics."""

    text: str                              # the compressed text
    original_length: int                   # len(original input)
    compressed_length: int                 # len(text)
    ratio: float                           # compressed_length / original_length (0.0–1.0)
    savings_pct: float                     # (1 - ratio) * 100
    level: int                             # compression level used
    preserved_spans: tuple[PreservedSpan, ...]  # what was kept intact

    def __str__(self) -> str:
        return self.text


_PRESERVE_WORDS = {
    "i", "a", "an", "the", "is", "am", "are", "was", "were", "be",
    "to", "of", "in", "on", "at", "by", "or", "and", "not", "no",
    "if", "it", "he", "she", "we", "do", "did", "has", "had", "can",
    "but", "for", "nor", "so", "yet", "all", "its", "my", "me",
    "up", "as", "go", "us", "ok", "yes", "true", "false", "null",
    "none", "def", "class", "return", "import", "from",
}

# Filler phrases that can be removed at level 4 for maximum compression
# These are common phrases that don't add significant meaning
_FILLER_PHRASES = [
    r"\b(you know|I mean|sort of|kind of|basically|actually|literally)\b",
    r"\b(I think|I believe|in my opinion|it seems)\b",
    r"\b(to be honest|honestly|frankly)\b",
    r"\b(just|really|very|quite|pretty)\s+",  # Intensifiers before adjectives
    r"\b(as you can see|as mentioned|as stated)\b",
    r"\b(for example|such as|e\.g\.|i\.e\.)\s*,?\s*",
    r"\b(in other words|that is to say)\b",
    r"\b(at the end of the day|at this point in time)\b",
    r"\b(needless to say|it goes without saying)\b",
]

# Extended vowels including accented characters for international language support
_VOWELS = set(
    "aeiouAEIOU"
    # Latin accented vowels (French, Spanish, German, Portuguese, etc.)
    "àáâãäåæèéêëìíîïðòóôõöøùúûüýÿ"
    "ÀÁÂÃÄÅÆÈÉÊËÌÍÎÏÐÒÓÔÕÖØÙÚÛÜÝŸ"
)

# Locale-specific stop words that should be preserved
# These are common words in each language that maintain readability
_LOCALE_STOP_WORDS: dict[str, set[str]] = {
    "fr": {  # French
        "le", "la", "les", "un", "une", "des",
        "de", "du", "et", "ou", "mais", "donc",
        "à", "au", "aux", "en", "dans", "sur",
        "pour", "par", "avec", "sans", "est", "sont",
        "il", "elle", "je", "tu", "nous", "vous",
    },
    "es": {  # Spanish
        "el", "la", "los", "las", "un", "una", "unos", "unas",
        "de", "del", "y", "o", "pero", "porque",
        "en", "con", "sin", "por", "para", "a", "al",
        "es", "son", "está", "están",
        "yo", "tú", "él", "ella", "nosotros", "vosotros",
    },
    "de": {  # German
        "der", "die", "das", "den", "dem", "des",
        "ein", "eine", "einer", "einem", "einen",
        "und", "oder", "aber", "doch",
        "in", "im", "am", "an", "auf", "aus", "bei",
        "mit", "von", "zu", "nach", "für",
        "ist", "sind", "war", "waren",
    },
    "pt": {  # Portuguese
        "o", "a", "os", "as", "um", "uma", "uns", "umas",
        "de", "do", "da", "dos", "das",
        "e", "ou", "mas", "porque",
        "em", "no", "na", "com", "por", "para",
        "é", "são", "está", "estão",
    },
    "it": {  # Italian
        "il", "lo", "la", "i", "gli", "le",
        "un", "uno", "una", "una",
        "di", "del", "della", "dei", "degli", "delle",
        "e", "o", "ma", "perché",
        "in", "nel", "con", "per", "da", "su",
        "è", "sono",
    },
}

_TOKEN_RE = re.compile(r"[a-zA-ZÀ-ÿ']+|[^a-zA-ZÀ-ÿ']+", re.UNICODE)
_ALPHA_RE = re.compile(r"[a-zA-ZÀ-ÿ']", re.UNICODE)

# --- Opt-out regions: content between these tags is never compressed ---
_COMPRESSOR_OFF_RE = re.compile(
    r"\[COMPRESSOR_OFF\](.*?)\[/COMPRESSOR_OFF\]",
    re.DOTALL,
)

# --- Structured data patterns ---
_FENCED_CODE_RE = re.compile(
    r"```[\w]*\n.*?```",
    re.DOTALL,
)

_INLINE_CODE_RE = re.compile(
    r"`[^`\n]+`",
)

# --- Markdown-specific patterns ---
_MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)]+)\)")  # [text](url) or ![alt](url)
_MD_HEADING_RE = re.compile(r"^(#{1,6}\s+)", re.MULTILINE)  # ## Heading
_MD_LIST_RE = re.compile(r"^(\s*[-*+]\s+|\s*\d+\.\s+)", re.MULTILINE)  # - item or 1. item
_MD_BLOCKQUOTE_RE = re.compile(r"^(>\s*)", re.MULTILINE)  # > quote
_MD_HR_RE = re.compile(r"^(---+|___+|\*\*\*+)\s*$", re.MULTILINE)  # horizontal rules
_MD_CODE_FENCE_RE = re.compile(r"^(```)", re.MULTILINE)  # code fence markers
_MD_BOLD_ITALIC_RE = re.compile(r"(\*\*|__|[*_])")  # **bold** or _italic_

# --- Patterns for spans that must never be compressed ---
# Order matters: longer/more specific patterns first.
_PRESERVE_PATTERNS = re.compile(
    r"|".join([
        # URLs  (http/https/ftp, or www.)
        r"https?://[^\s]+",
        r"ftp://[^\s]+",
        r"www\.[^\s]+",
        # Email addresses
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        # Phone numbers: international (+1-555-123-4567) and common formats
        r"\+?\d[\d\-.\s()]{6,}\d",
        # UUIDs  (8-4-4-4-12 hex)
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        # Hex IDs (>= 8 hex digits)
        r"\b[0-9a-fA-F]{8,}\b",
        # Alphanumeric IDs with mixed digits/letters (e.g. "ABC123", "usr_42x9")
        r"\b[A-Za-z0-9_\-]*\d[A-Za-z0-9_\-]*[A-Za-z][A-Za-z0-9_\-]*\b",
        r"\b[A-Za-z0-9_\-]*[A-Za-z][A-Za-z0-9_\-]*\d[A-Za-z0-9_\-]*\b",
    ]),
)


def _find_balanced_end(text: str, start: int, open_char: str, close_char: str) -> int | None:
    """Find the matching closing character for a balanced structure.

    Args:
        text: The text to search in.
        start: Position just after the opening character.
        open_char: Opening character (e.g., '{', '[', '<').
        close_char: Closing character (e.g., '}', ']', '>').

    Returns:
        Position of the matching closing character, or None if not found.
    """
    count = 1
    i = start
    in_string = False
    escape = False

    while i < len(text) and count > 0:
        ch = text[i]

        # Handle string literals (for JSON)
        if ch == '"' and not escape and open_char in '{[':
            in_string = not in_string
        elif ch == '\\' and in_string:
            escape = not escape
            i += 1
            continue

        if not in_string:
            if ch == open_char:
                count += 1
            elif ch == close_char:
                count -= 1

        escape = False
        i += 1

    return i if count == 0 else None


def _find_json_block(text: str, start: int) -> tuple[int, int] | None:
    """Try to find a JSON object or array starting at position start.

    Returns:
        (start, end) tuple if valid JSON-like block found, None otherwise.
    """
    if start >= len(text):
        return None

    open_char = text[start]
    if open_char not in '{[':
        return None

    # Only treat as JSON if followed by " or digit (to avoid matching plain prose like "[word]")
    if start + 1 < len(text):
        next_chars = text[start + 1:start + 10].lstrip()
        if next_chars and next_chars[0] not in '"{[0123456789-tfn':  # JSON value starters
            return None

    close_char = '}' if open_char == '{' else ']'
    end = _find_balanced_end(text, start + 1, open_char, close_char)

    if end:
        return (start, end)
    return None


def _find_xml_block(text: str, start: int) -> tuple[int, int] | None:
    """Try to find an XML/HTML block starting at position start.

    Returns:
        (start, end) tuple if valid XML-like block found, None otherwise.
    """
    if start >= len(text) or text[start] != '<':
        return None

    # Match opening tag
    tag_match = re.match(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>', text[start:])
    if not tag_match:
        return None

    tag_name = tag_match.group(1)
    tag_end = start + tag_match.end()

    # Check for self-closing tag
    if text[start:tag_end].rstrip().endswith('/>'):
        return (start, tag_end)

    # Find matching closing tag
    close_pattern = f'</{tag_name}>'
    close_pos = text.find(close_pattern, tag_end)

    if close_pos != -1:
        return (start, close_pos + len(close_pattern))

    return None


def _extract_structured_data_spans(text: str) -> list[tuple[int, int, str]]:
    """Extract all structured data spans (code blocks, JSON, XML).

    Returns:
        List of (start, end, kind) tuples sorted by start position.
    """
    spans: list[tuple[int, int, str]] = []

    # Fenced code blocks
    for match in _FENCED_CODE_RE.finditer(text):
        spans.append((match.start(), match.end(), "fenced_code"))

    # Inline code
    for match in _INLINE_CODE_RE.finditer(text):
        spans.append((match.start(), match.end(), "inline_code"))

    # JSON blocks (scan for { and [ that look like JSON)
    i = 0
    while i < len(text):
        if text[i] in '{[':
            result = _find_json_block(text, i)
            if result:
                start, end = result
                spans.append((start, end, "json"))
                i = end
                continue
        i += 1

    # XML/HTML blocks
    i = 0
    while i < len(text):
        if text[i] == '<':
            result = _find_xml_block(text, i)
            if result:
                start, end = result
                spans.append((start, end, "xml"))
                i = end
                continue
        i += 1

    # Sort by start position and merge overlapping spans
    spans.sort(key=lambda x: x[0])

    # Remove overlaps (keep earlier/longer spans)
    merged: list[tuple[int, int, str]] = []
    for span in spans:
        start, end, kind = span
        # Check if this overlaps with any existing span
        overlaps = False
        for existing in merged:
            ex_start, ex_end, _ = existing
            if not (end <= ex_start or start >= ex_end):
                overlaps = True
                break
        if not overlaps:
            merged.append(span)

    return merged


def _compress_markdown(
    text: str,
    level: int,
    collect_spans: list[tuple[int, int, str]] | None = None,
    custom_patterns: list[re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
) -> str:
    """Compress text while preserving markdown syntax.

    Markdown elements like headings, links, lists, etc. have their markers preserved,
    but the text content is still compressed.

    Args:
        text: Text to compress.
        level: Compression level.
        collect_spans: Optional span collection list.
        custom_patterns: Optional custom regex patterns.
        preserve_words: Optional custom word set.

    Returns:
        Compressed markdown text.
    """
    compressed_offset = 0

    # Process line by line to handle markdown line-based syntax
    lines = text.split("\n")
    compressed_lines: list[str] = []

    for line_idx, line in enumerate(lines):
        # Horizontal rules - preserve entirely
        if _MD_HR_RE.match(line):
            compressed_lines.append(line)
            if collect_spans:
                collect_spans.append((
                    compressed_offset,
                    compressed_offset + len(line),
                    "markdown_hr"
                ))
            compressed_offset += len(line) + (1 if line_idx < len(lines) - 1 else 0)
            continue

        # Headings - preserve markers, compress text
        heading_match = _MD_HEADING_RE.match(line)
        if heading_match:
            marker = heading_match.group(1)
            heading_text = line[len(marker):]
            # Compress the heading text
            compressed_heading = _compress_with_preserve_patterns(
                heading_text, level, None, custom_patterns, preserve_words
            )
            compressed_line = marker + compressed_heading
            compressed_lines.append(compressed_line)
            compressed_offset += len(compressed_line) + (1 if line_idx < len(lines) - 1 else 0)
            continue

        # List items - preserve markers, compress text
        list_match = _MD_LIST_RE.match(line)
        if list_match:
            marker = list_match.group(1)
            item_text = line[len(marker):]
            compressed_item = _compress_with_preserve_patterns(
                item_text, level, None, custom_patterns, preserve_words
            )
            compressed_line = marker + compressed_item
            compressed_lines.append(compressed_line)
            compressed_offset += len(compressed_line) + (1 if line_idx < len(lines) - 1 else 0)
            continue

        # Blockquotes - preserve markers, compress text
        quote_match = _MD_BLOCKQUOTE_RE.match(line)
        if quote_match:
            marker = quote_match.group(1)
            quote_text = line[len(marker):]
            compressed_quote = _compress_with_preserve_patterns(
                quote_text, level, None, custom_patterns, preserve_words
            )
            compressed_line = marker + compressed_quote
            compressed_lines.append(compressed_line)
            compressed_offset += len(compressed_line) + (1 if line_idx < len(lines) - 1 else 0)
            continue

        # For other lines, handle inline markdown like links
        # Links: [text](url) - compress text, preserve url
        line_result = []
        line_pos = 0

        for link_match in _MD_LINK_RE.finditer(line):
            # Add text before link (compressed)
            if link_match.start() > line_pos:
                before_text = line[line_pos:link_match.start()]
                compressed_before = _compress_with_preserve_patterns(
                    before_text, level, None, custom_patterns, preserve_words
                )
                line_result.append(compressed_before)

            # Handle link: compress link text, preserve URL
            is_image = link_match.group(0).startswith("!")
            link_text = link_match.group(1)
            url = link_match.group(2)

            compressed_link_text = _compress_with_preserve_patterns(
                link_text, level, None, custom_patterns, preserve_words
            )

            # Reconstruct link
            if is_image:
                line_result.append(f"![{compressed_link_text}]({url})")
            else:
                line_result.append(f"[{compressed_link_text}]({url})")

            line_pos = link_match.end()

        # Add remaining text after last link
        if line_pos < len(line):
            remaining = line[line_pos:]
            compressed_remaining = _compress_with_preserve_patterns(
                remaining, level, None, custom_patterns, preserve_words
            )
            line_result.append(compressed_remaining)

        compressed_line = "".join(line_result) if line_result else _compress_with_preserve_patterns(
            line, level, None, custom_patterns, preserve_words
        )
        compressed_lines.append(compressed_line)
        compressed_offset += len(compressed_line) + (1 if line_idx < len(lines) - 1 else 0)

    return "\n".join(compressed_lines)


def _remove_double_letters(word: str) -> str:
    """Remove consecutive duplicate letters: 'letter' -> 'leter'."""
    if len(word) <= 2:
        return word
    chars = [word[0]]
    for ch in word[1:]:
        if ch.lower() != chars[-1].lower():
            chars.append(ch)
    return "".join(chars)


def _remove_interior_vowels(word: str) -> str:
    """Remove vowels from the interior of the word.

    Keep the first letter, last letter, and consonants.
    Also keep a vowel if removing it would create 4+ consecutive consonants.
    """
    if len(word) <= 3:
        return word

    first, middle, last = word[0], word[1:-1], word[-1]

    compressed: list[str] = []
    consonant_streak = 1 if first.lower() not in _VOWELS else 0

    for ch in middle:
        if ch in _VOWELS or ch.lower() in _VOWELS:
            if consonant_streak >= 3:
                compressed.append(ch)
                consonant_streak = 0
        else:
            compressed.append(ch)
            consonant_streak += 1

    return first + "".join(compressed) + last


def _aggressive_trim(word: str) -> str:
    """For level 3: truncate long words, keeping recognizable prefix."""
    if len(word) > 6:
        return word[:5] + word[-1]
    return word


def _is_proper_noun(word: str) -> bool:
    """Heuristic: a word that starts with an uppercase letter (and isn't all-caps) is likely a proper noun."""
    return len(word) > 1 and word[0].isupper() and not word.isupper() and not word[1:].isupper()


def _compress_word(word: str, level: int, preserve_words: set[str] | None = None) -> str:
    """Compress a single word according to the given level.

    Args:
        word: Word to compress.
        level: Compression level.
        preserve_words: Optional custom word set to merge with built-in.
    """
    # Merge built-in and custom preserve words
    effective_preserve_words = _PRESERVE_WORDS if preserve_words is None else _PRESERVE_WORDS | preserve_words

    if len(word) <= 3 or word.lower() in effective_preserve_words:
        return word

    if any(ch in word for ch in "@:/_.#{}[]()"):
        return word

    # Preserve ALL-CAPS acronyms
    if word.isupper():
        return word

    # Preserve proper nouns / names (capitalised words)
    if _is_proper_noun(word):
        return word

    # Level 1: remove doubled letters
    result = _remove_double_letters(word)
    if level == 1:
        return result

    # Level 2: also remove interior vowels
    result = _remove_interior_vowels(result)
    if level == 2:
        return result

    # Level 3: also aggressively trim long words
    result = _aggressive_trim(result)
    return result


def _prune_sentences(text: str) -> str:
    """Apply sentence-level pruning for level 4 compression.

    This removes filler phrases and deduplicates lines to achieve maximum compression
    while maintaining semantic content.

    Args:
        text: Text to prune.

    Returns:
        Pruned text with filler phrases removed and lines deduplicated.
    """
    # Remove filler phrases
    for pattern in _FILLER_PHRASES:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)

    # Deduplicate consecutive lines (case-insensitive)
    lines = text.split("\n")
    deduped: list[str] = []
    prev_normalized = ""

    for line in lines:
        # Normalize for comparison (lowercase, strip)
        normalized = line.strip().lower()
        if normalized and normalized != prev_normalized:
            deduped.append(line)
            prev_normalized = normalized
        elif not normalized:
            # Keep blank lines but don't update prev
            deduped.append(line)

    return "\n".join(deduped)


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace by collapsing runs and limiting blank lines.

    - Strips trailing whitespace per line
    - Collapses runs of spaces/tabs to single space (preserving leading indent)
    - Collapses 3+ consecutive blank lines to 2 blank lines
    - Strips leading/trailing blank lines from full text
    """
    lines = text.split("\n")
    result: list[str] = []
    blank_streak = 0

    for line in lines:
        # Split into leading whitespace and content
        stripped = line.rstrip()
        if not stripped:
            blank_streak += 1
            # Keep max 2 consecutive blank lines
            if blank_streak <= 2:
                result.append("")
        else:
            blank_streak = 0
            # Preserve leading whitespace, but normalize the rest
            leading_ws = line[:len(line) - len(line.lstrip())]
            content = stripped[len(leading_ws):]
            # Collapse runs of spaces/tabs in content
            content = re.sub(r"[ \t]+", " ", content)
            result.append(leading_ws + content)

    # Strip leading/trailing blank lines only (not whitespace)
    while result and result[0] == "":
        result.pop(0)
    while result and result[-1] == "":
        result.pop()

    return "\n".join(result)


def _compress_segment(segment: str, level: int, preserve_words: set[str] | None = None) -> str:
    """Compress a plain-text segment (no preserved spans inside).

    Args:
        segment: Text segment to compress.
        level: Compression level.
        preserve_words: Optional custom word set to merge with built-in.
    """
    tokens = _TOKEN_RE.findall(segment)
    parts: list[str] = []
    for token in tokens:
        if _ALPHA_RE.match(token):
            parts.append(_compress_word(token, level, preserve_words))
        else:
            parts.append(token)
    return "".join(parts)


def _compress_with_preserve_patterns(
    text: str,
    level: int,
    collect_spans: list[tuple[int, int, str]] | None = None,
    custom_patterns: list[re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
) -> str:
    """Compress *text* while keeping auto-detected spans (URLs, emails, structured data, etc.) intact.

    Args:
        text: Text to compress.
        level: Compression level.
        collect_spans: Optional list to collect (start, end, kind) tuples of preserved spans.
        custom_patterns: Optional custom regex patterns to preserve.
        preserve_words: Optional custom word set to merge with built-in.
    """
    # Collect structured data spans
    structured_spans = _extract_structured_data_spans(text)

    # Collect custom pattern spans (checked first, higher priority)
    regex_spans: list[tuple[int, int, str]] = []
    if custom_patterns:
        for pattern in custom_patterns:
            for m in pattern.finditer(text):
                regex_spans.append((m.start(), m.end(), "custom_pattern"))

    # Collect built-in regex-based preserve patterns
    for m in _PRESERVE_PATTERNS.finditer(text):
        regex_spans.append((m.start(), m.end(), "preserve"))

    # Merge all spans and sort by start position
    all_spans = structured_spans + regex_spans
    all_spans.sort(key=lambda x: x[0])

    # Remove overlaps (keep earlier spans when there's overlap)
    merged_spans: list[tuple[int, int, str]] = []
    for span in all_spans:
        start, end, kind = span
        overlaps = False
        for existing in merged_spans:
            ex_start, ex_end, _ = existing
            if not (end <= ex_start or start >= ex_end):
                overlaps = True
                break
        if not overlaps:
            merged_spans.append(span)

    if not merged_spans:
        return _compress_segment(text, level, preserve_words)

    result: list[str] = []
    prev_end = 0
    compressed_offset = 0  # Track position in compressed output

    for start, end, kind in merged_spans:
        if start > prev_end:
            compressed_segment = _compress_segment(text[prev_end:start], level, preserve_words)
            result.append(compressed_segment)
            compressed_offset += len(compressed_segment)

        preserved_text = text[start:end]
        result.append(preserved_text)

        # Record the span in compressed output coordinates
        if collect_spans is not None:
            collect_spans.append((compressed_offset, compressed_offset + len(preserved_text), kind))

        compressed_offset += len(preserved_text)
        prev_end = end

    if prev_end < len(text):
        result.append(_compress_segment(text[prev_end:], level, preserve_words))

    return "".join(result)


def compress(
    text: str,
    level: int = 2,
    normalize: bool = True,
    preserve_patterns: list[str | re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
    markdown: bool = False,
    locale: str | None = None,
) -> str:
    """Remove letters from text to make it smaller but still understandable by an LLM.

    Emails, URLs, phone numbers, IDs, UUIDs, and proper nouns are left intact.
    Text enclosed in ``[COMPRESSOR_OFF]...[/COMPRESSOR_OFF]`` tags is passed
    through verbatim (the tags themselves are stripped from the output).

    Args:
        text: Input text to compress.
        level: Compression aggressiveness (1=light, 2=medium, 3=heavy, 4=maximum with sentence pruning).
        normalize: Whether to normalize whitespace (collapse runs, limit blank lines).
        preserve_patterns: Optional list of custom regex patterns (strings or compiled) to preserve.
        preserve_words: Optional set of custom words to preserve (merged with built-in set).
        markdown: Whether to use markdown-aware compression (preserves headings, lists, links, etc.).
        locale: Optional language code (e.g., 'fr', 'es', 'de') to preserve locale-specific stop words.

    Returns:
        Compressed text string.

    Raises:
        ValueError: If a preserve_pattern string is not a valid regex, or if level is not 1-4, or if level is not 1-4.
    """
    # Validate level
    if not (1 <= level <= 4):
        raise ValueError(f"Compression level must be 1-4, got {level}")

    # Apply sentence pruning for level 4 before other compression
    if level == 4:
        text = _prune_sentences(text)
        # Use level 3 compression after pruning
        effective_level = 3
    else:
        effective_level = level

    # Compile custom patterns
    compiled_patterns: list[re.Pattern[str]] | None = None
    if preserve_patterns:
        compiled_patterns = []
        for pattern in preserve_patterns:
            if isinstance(pattern, str):
                try:
                    compiled_patterns.append(re.compile(pattern))
                except re.error as e:
                    raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
            else:
                compiled_patterns.append(pattern)

    # Merge locale-specific stop words with custom preserve words
    merged_preserve_words = preserve_words.copy() if preserve_words else set()
    if locale and locale in _LOCALE_STOP_WORDS:
        merged_preserve_words.update(_LOCALE_STOP_WORDS[locale])
    final_preserve_words = merged_preserve_words if merged_preserve_words else None

    # Apply whitespace normalization first, but preserve COMPRESSOR_OFF regions
    if normalize:
        off_regions = list(_COMPRESSOR_OFF_RE.finditer(text))

        if off_regions:
            # Normalize only the parts outside COMPRESSOR_OFF tags
            # Keep the tags and their content intact for now
            parts: list[str] = []
            prev_end = 0

            for match in off_regions:
                start, end = match.start(), match.end()
                if start > prev_end:
                    parts.append(_normalize_whitespace(text[prev_end:start]))
                # Keep the entire match (tags + content) without normalization
                parts.append(match.group(0))
                prev_end = end

            if prev_end < len(text):
                parts.append(_normalize_whitespace(text[prev_end:]))

            text = "".join(parts)
        else:
            text = _normalize_whitespace(text)

    # Route to markdown-aware compression if requested
    if markdown:
        off_regions = list(_COMPRESSOR_OFF_RE.finditer(text))
        if not off_regions:
            return _compress_markdown(text, effective_level, None, compiled_patterns, final_preserve_words)

        # Handle COMPRESSOR_OFF regions with markdown mode
        md_parts: list[str] = []
        prev_end = 0
        for match in off_regions:
            start, end = match.start(), match.end()
            if start > prev_end:
                md_parts.append(_compress_markdown(
                    text[prev_end:start], effective_level, None, compiled_patterns, final_preserve_words
                ))
            md_parts.append(match.group(1))
            prev_end = end
        if prev_end < len(text):
            md_parts.append(_compress_markdown(
                text[prev_end:], effective_level, None, compiled_patterns, final_preserve_words
            ))
        return "".join(md_parts)

    # Handle [COMPRESSOR_OFF]...[/COMPRESSOR_OFF] regions (standard mode)
    off_regions = list(_COMPRESSOR_OFF_RE.finditer(text))

    if not off_regions:
        return _compress_with_preserve_patterns(text, effective_level, None, compiled_patterns, final_preserve_words)

    off_parts: list[str] = []
    prev_end = 0

    for match in off_regions:
        start, end = match.start(), match.end()
        # Compress the text before this off-region
        if start > prev_end:
            off_parts.append(_compress_with_preserve_patterns(
                text[prev_end:start], effective_level, None, compiled_patterns, final_preserve_words
            ))
        # Keep the content between the tags verbatim (tags stripped)
        off_parts.append(match.group(1))
        prev_end = end

    # Compress any remaining text after the last off-region
    if prev_end < len(text):
        off_parts.append(_compress_with_preserve_patterns(
            text[prev_end:], effective_level, None, compiled_patterns, final_preserve_words
        ))

    return "".join(off_parts)


def compress_with_stats(
    text: str,
    level: int = 2,
    normalize: bool = True,
    preserve_patterns: list[str | re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
    markdown: bool = False,
    locale: str | None = None,
) -> CompressionResult:
    """Compress text and return detailed statistics about the compression.

    Args:
        text: Input text to compress.
        level: Compression aggressiveness (1=light, 2=medium, 3=heavy, 4=maximum with sentence pruning).
        normalize: Whether to normalize whitespace.
        preserve_patterns: Optional list of custom regex patterns to preserve.
        preserve_words: Optional set of custom words to preserve.
        markdown: Whether to use markdown-aware compression.
        locale: Optional language code (e.g., 'fr', 'es', 'de') to preserve locale-specific stop words.

    Returns:
        CompressionResult with compressed text and detailed statistics.

    Raises:
        ValueError: If a preserve_pattern string is not a valid regex, or if level is not 1-4.
    """
    # Validate level
    if not (1 <= level <= 4):
        raise ValueError(f"Compression level must be 1-4, got {level}")

    # Apply sentence pruning for level 4
    if level == 4:
        text = _prune_sentences(text)
        effective_level = 3
    else:
        effective_level = level

    # Compile custom patterns
    compiled_patterns: list[re.Pattern[str]] | None = None
    if preserve_patterns:
        compiled_patterns = []
        for pattern in preserve_patterns:
            if isinstance(pattern, str):
                try:
                    compiled_patterns.append(re.compile(pattern))
                except re.error as e:
                    raise ValueError(f"Invalid regex pattern '{pattern}': {e}") from e
            else:
                compiled_patterns.append(pattern)

    # Merge locale-specific stop words with custom preserve words
    merged_preserve_words = preserve_words.copy() if preserve_words else set()
    if locale and locale in _LOCALE_STOP_WORDS:
        merged_preserve_words.update(_LOCALE_STOP_WORDS[locale])
    final_preserve_words = merged_preserve_words if merged_preserve_words else None

    original_text = text
    original_length = len(original_text)

    # Apply whitespace normalization (same as compress())
    if normalize:
        off_regions = list(_COMPRESSOR_OFF_RE.finditer(text))

        if off_regions:
            parts: list[str] = []
            prev_end = 0

            for match in off_regions:
                start, end = match.start(), match.end()
                if start > prev_end:
                    parts.append(_normalize_whitespace(text[prev_end:start]))
                parts.append(match.group(0))
                prev_end = end

            if prev_end < len(text):
                parts.append(_normalize_whitespace(text[prev_end:]))

            text = "".join(parts)
        else:
            text = _normalize_whitespace(text)

    # Track preserved spans
    collected_spans: list[tuple[int, int, str]] = []

    # Route to markdown-aware compression if requested
    if markdown:
        off_regions = list(_COMPRESSOR_OFF_RE.finditer(text))

        if not off_regions:
            compressed_text = _compress_markdown(
                text, effective_level, collected_spans, compiled_patterns, final_preserve_words
            )
        else:
            md_stat_parts: list[str] = []
            prev_end = 0
            compressed_offset = 0

            for match in off_regions:
                start, end = match.start(), match.end()
                if start > prev_end:
                    md_seg_spans: list[tuple[int, int, str]] = []
                    compressed_segment = _compress_markdown(
                        text[prev_end:start], effective_level, md_seg_spans, compiled_patterns, final_preserve_words
                    )
                    md_stat_parts.append(compressed_segment)

                    # Adjust span positions
                    for span_start, span_end, kind in md_seg_spans:
                        collected_spans.append((
                            compressed_offset + span_start,
                            compressed_offset + span_end,
                            kind
                        ))

                    compressed_offset += len(compressed_segment)

                # Record COMPRESSOR_OFF span
                content = match.group(1)
                md_stat_parts.append(content)
                collected_spans.append((compressed_offset, compressed_offset + len(content), "compressor_off"))
                compressed_offset += len(content)
                prev_end = end

            if prev_end < len(text):
                md_seg_spans_tail: list[tuple[int, int, str]] = []
                compressed_segment = _compress_markdown(
                    text[prev_end:], effective_level, md_seg_spans_tail, compiled_patterns, final_preserve_words
                )
                md_stat_parts.append(compressed_segment)

                for span_start, span_end, kind in md_seg_spans_tail:
                    collected_spans.append((
                        compressed_offset + span_start,
                        compressed_offset + span_end,
                        kind
                    ))

            compressed_text = "".join(md_stat_parts)
    else:
        # Handle [COMPRESSOR_OFF]...[/COMPRESSOR_OFF] regions (standard mode)
        off_regions = list(_COMPRESSOR_OFF_RE.finditer(text))

        if not off_regions:
            compressed_text = _compress_with_preserve_patterns(
                text, effective_level, collected_spans, compiled_patterns, final_preserve_words
            )
        else:
            stat_parts: list[str] = []
            prev_end = 0
            compressed_offset = 0

            for match in off_regions:
                start, end = match.start(), match.end()
                if start > prev_end:
                    seg_spans: list[tuple[int, int, str]] = []
                    compressed_segment = _compress_with_preserve_patterns(
                        text[prev_end:start], effective_level, seg_spans, compiled_patterns, final_preserve_words
                    )
                    stat_parts.append(compressed_segment)

                    # Adjust span positions to account for offset
                    for span_start, span_end, kind in seg_spans:
                        collected_spans.append((
                            compressed_offset + span_start,
                            compressed_offset + span_end,
                            kind
                        ))

                    compressed_offset += len(compressed_segment)

                # Record COMPRESSOR_OFF span
                content = match.group(1)
                stat_parts.append(content)
                collected_spans.append((compressed_offset, compressed_offset + len(content), "compressor_off"))
                compressed_offset += len(content)
                prev_end = end

            if prev_end < len(text):
                seg_spans_tail: list[tuple[int, int, str]] = []
                compressed_segment = _compress_with_preserve_patterns(
                    text[prev_end:], effective_level, seg_spans_tail, compiled_patterns, final_preserve_words
                )
                stat_parts.append(compressed_segment)

                for span_start, span_end, kind in seg_spans_tail:
                    collected_spans.append((
                        compressed_offset + span_start,
                        compressed_offset + span_end,
                        kind
                    ))

            compressed_text = "".join(stat_parts)

    compressed_length = len(compressed_text)
    ratio = compressed_length / original_length if original_length > 0 else 1.0
    savings_pct = (1 - ratio) * 100

    # Convert collected spans to PreservedSpan objects
    preserved_spans = tuple(
        PreservedSpan(
            start=start,
            end=end,
            text=compressed_text[start:end],
            kind=kind
        )
        for start, end, kind in collected_spans
    )

    return CompressionResult(
        text=compressed_text,
        original_length=original_length,
        compressed_length=compressed_length,
        ratio=ratio,
        savings_pct=savings_pct,
        level=level,
        preserved_spans=preserved_spans
    )


def compress_stream(
    chunks: Iterable[str],
    level: int = 2,
    normalize: bool = True,
    preserve_patterns: list[str | re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
    markdown: bool = False,
    locale: str | None = None,
    buffer_size: int = 4096,
) -> Generator[str, None, None]:
    """Compress text from an iterable of chunks, yielding compressed chunks.

    This function processes text in a streaming fashion, making it suitable for
    large files or data that arrives incrementally. Text is buffered until word
    boundaries to ensure proper compression.

    Args:
        chunks: Iterable of text chunks to compress.
        level: Compression aggressiveness (1=light, 2=medium, 3=heavy).
        normalize: Whether to normalize whitespace.
        preserve_patterns: Optional list of custom regex patterns to preserve.
        preserve_words: Optional set of custom words to preserve.
        markdown: Whether to use markdown-aware compression.
        locale: Optional language code for locale-specific stop words.
        buffer_size: Target size for internal buffer before yielding (default: 4096).

    Yields:
        Compressed text chunks.

    Raises:
        ValueError: If a preserve_pattern string is not a valid regex.

    Example:
        >>> chunks = ["This is a ", "test of streaming ", "compression."]
        >>> for compressed_chunk in compress_stream(chunks, level=2):
        ...     print(compressed_chunk, end="")
    """
    buffer = []
    buffer_len = 0

    for chunk in chunks:
        if not chunk:
            continue

        buffer.append(chunk)
        buffer_len += len(chunk)

        # Process buffer when it reaches target size and we're at a word boundary
        if buffer_len >= buffer_size:
            text = "".join(buffer)

            # Find last whitespace to split at word boundary
            last_space = -1
            for i in range(len(text) - 1, max(0, len(text) - 100), -1):
                if text[i].isspace():
                    last_space = i + 1
                    break

            if last_space > 0:
                # Process up to the word boundary
                to_process = text[:last_space]
                compressed = compress(
                    to_process,
                    level=level,
                    normalize=normalize,
                    preserve_patterns=preserve_patterns,
                    preserve_words=preserve_words,
                    markdown=markdown,
                    locale=locale,
                )
                if compressed:
                    yield compressed

                # Keep remainder in buffer
                buffer = [text[last_space:]]
                buffer_len = len(buffer[0])

    # Flush remaining buffer
    if buffer:
        text = "".join(buffer)
        if text:
            compressed = compress(
                text,
                level=level,
                normalize=normalize,
                preserve_patterns=preserve_patterns,
                preserve_words=preserve_words,
                markdown=markdown,
                locale=locale,
            )
            if compressed:
                yield compressed


def compress_file(
    file_path: str,
    level: int = 2,
    normalize: bool = True,
    preserve_patterns: list[str | re.Pattern[str]] | None = None,
    preserve_words: set[str] | None = None,
    markdown: bool = False,
    locale: str | None = None,
    chunk_size: int = 8192,
    encoding: str = "utf-8",
) -> Generator[str, None, None]:
    """Compress a file in streaming fashion, yielding compressed chunks.

    This function reads a file in chunks and compresses it incrementally,
    making it memory-efficient for large files.

    Args:
        file_path: Path to the file to compress.
        level: Compression aggressiveness (1=light, 2=medium, 3=heavy).
        normalize: Whether to normalize whitespace.
        preserve_patterns: Optional list of custom regex patterns to preserve.
        preserve_words: Optional set of custom words to preserve.
        markdown: Whether to use markdown-aware compression.
        locale: Optional language code for locale-specific stop words.
        chunk_size: Size of chunks to read from file (default: 8192).
        encoding: File encoding (default: utf-8).

    Yields:
        Compressed text chunks.

    Raises:
        ValueError: If a preserve_pattern string is not a valid regex.
        FileNotFoundError: If the file does not exist.
        IOError: If there's an error reading the file.

    Example:
        >>> for chunk in compress_file("large_document.txt", level=2):
        ...     output_file.write(chunk)
    """
    def read_chunks() -> Generator[str, None, None]:
        with open(file_path, encoding=encoding) as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    yield from compress_stream(
        read_chunks(),
        level=level,
        normalize=normalize,
        preserve_patterns=preserve_patterns,
        preserve_words=preserve_words,
        markdown=markdown,
        locale=locale,
        buffer_size=chunk_size,
    )
