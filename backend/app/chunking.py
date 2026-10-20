"""Structure-aware chunking for legal documents (see docs/CHUNKING_STRATEGY.md).

Elements are grouped into clauses: a clause starts at a heading or at a paragraph
that opens with a clause number ("4. Term and Termination.", "12.2", "§3",
"Section 4", "ARTICLE IV"). Small sibling clauses are merged, long ones split at
paragraph (sub-clause) boundaries first and sentences last. Every chunk keeps the
literal text for quoting plus a breadcrumb used only for its embedding."""

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.config import get_settings
from app.parsing import Element

log = logging.getLogger(__name__)

_MAX_LABEL_CHARS = 80

# Numbered clause at the start of a paragraph. Digit clauses need a trailing dot
# ("4.") or a dotted number ("12.2"), followed by something that looks like a
# title or sub-clause, so "3.5 million" or "2020 revenue" don't count.
_CLAUSE_RE = re.compile(
    r"""^(?:
        (?P<sect>§+\s*\d+(?:\.\d+)*[a-z]?)
      | (?P<word>(?i:section|article|clause)\s+(?:\d+(?:\.\d+)*|[IVXLC]+)\b)
      | (?P<num>\d{1,3}\.(?:\d{1,3}\.?)*|\d{1,3}(?:\.\d{1,3})+)
    )(?=\s+[A-Z(“"'])""",
    re.VERBOSE,
)
# Headings are already known to be headings, so a bare "7 Payment" is fine there.
_HEADING_NUM_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)\.?(?:\s|$)")
_TOP_LEVEL_RE = re.compile(r"^(exhibit|schedule|annex|appendix|attachment|addendum)\b", re.IGNORECASE)
# '"Term" means ...', '(a) "Term" shall mean ...', '“Term” has the meaning ...'
_DEFINITION_RE = re.compile(
    r"""^(?:\(?[a-z0-9]{1,4}[.)]\s*)?[“"][^”"]{1,80}[”"]\s*(?:\([^)]{0,80}\)\s*)?
        (?:shall\s+)?(?:means?|has\s+the\s+meaning|includes?|refers?\s+to)\b""",
    re.VERBOSE | re.IGNORECASE,
)
_SENTENCE_END_RE = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z(“\"])")


@dataclass
class ChunkDraft:
    content: str
    embed_text: str
    heading_path: str | None
    section: str | None
    element_type: str  # "text" | "table" | "definition"
    source: str
    page_start: int | None
    page_end: int | None
    bboxes: list[dict]
    token_count: int
    # Path of the top-level section the chunk belongs to ("2. VOTOCAST'S OBLIGATIONS",
    # "EXHIBIT C"); chunks sharing it form one SectionDraft.
    section_path: tuple[str, ...] = ()


@dataclass
class SectionDraft:
    """A top-level section: retrieval sends it whole when it fits the budget, and
    it gets its own embedding so a question about the section as a whole
    ("VOTOCAST's obligations") can match it even when no single chunk does."""

    heading_path: str | None
    chunk_indexes: list[int]
    embed_text: str
    token_count: int


@dataclass
class _Heading:
    depth: int
    label: str
    numbered: bool


@dataclass
class _Segment:
    kind: str
    path: tuple[str, ...]
    top: tuple[str, ...]  # path up to the top-level section
    elements: list[Element] = field(default_factory=list)


# ---------------------------------------------------------------- tokens


@lru_cache
def _tokenizer():
    name = get_settings().chunk_tokenizer
    try:
        from tokenizers import Tokenizer

        return Tokenizer.from_pretrained(name)
    except Exception:
        log.warning("Couldn't load tokenizer %s; estimating tokens as characters / 4", name, exc_info=True)
        return None


def count_tokens(text: str) -> int:
    tokenizer = _tokenizer()
    if tokenizer is None:
        return max(1, len(text) // 4)
    return len(tokenizer.encode(text, add_special_tokens=False).ids)


# ---------------------------------------------------------------- structure


def clause_label(text: str) -> str | None:
    """'4. Term and Termination. (a) The initial…' -> '4. Term and Termination'."""
    match = _CLAUSE_RE.match(text)
    if not match:
        return None
    number = " ".join(match.group(0).split())
    rest = text[match.end() :].lstrip()
    title = re.match(r"([A-Z][^.;:]{0,70}?)[.:](?:\s|$)", rest)
    if title and _looks_like_title(title.group(1)):
        return _short(f"{number} {title.group(1)}")
    return _short(number)


def _looks_like_title(text: str) -> bool:
    """'Term and Termination' yes, 'The Supplier shall deliver' no."""
    words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) > 3]
    return not words or sum(w[0].isupper() for w in words) / len(words) >= 0.6


def is_definition(text: str) -> bool:
    return bool(_DEFINITION_RE.match(text))


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_LABEL_CHARS else text[: _MAX_LABEL_CHARS - 1].rstrip() + "…"


def _numbered_depth(number: str) -> int:
    return len([p for p in re.split(r"[.\s]+", number.strip("§ ")) if p])


def _push(stack: list[_Heading], heading: _Heading) -> None:
    while stack and stack[-1].depth >= heading.depth:
        stack.pop()
    stack.append(heading)


def _heading_for(text: str, stack: list[_Heading], is_heading: bool, seen_numbered: bool) -> _Heading | None:
    """Where a heading or clause-opening paragraph sits in the outline, or None."""
    text = text.strip()
    # Clauses inside an exhibit/schedule nest under it.
    base = 1 if any(_TOP_LEVEL_RE.match(h.label) for h in stack if not h.numbered) else 0

    if is_heading and _TOP_LEVEL_RE.match(text):
        return _Heading(1, _short(text), numbered=False)

    if match := _CLAUSE_RE.match(text):
        if match.group("word"):
            number = match.group("word").split(None, 1)[1]
            depth = _numbered_depth(number) if number[0].isdigit() else 1
        else:
            depth = _numbered_depth(match.group("sect") or match.group("num"))
        # A heading's full text is its label; a paragraph only contributes "4. Title".
        return _Heading(base + depth, _short(text) if is_heading else clause_label(text), numbered=True)

    if is_heading:
        if match := _HEADING_NUM_RE.match(text):
            return _Heading(base + _numbered_depth(match.group(1)), _short(text), numbered=True)
        if not seen_numbered:
            # Before the first numbered clause: the document's own title block.
            return _Heading(0, _short(text), numbered=False)
        last_numbered = next((h.depth for h in reversed(stack) if h.numbered), base)
        return _Heading(last_numbered + 1, _short(text), numbered=False)
    return None


def _segments(elements: list[Element]) -> list[_Segment]:
    stack: list[_Heading] = []
    segments: list[_Segment] = []

    def path() -> tuple[str, ...]:
        return tuple(h.label for h in stack)

    def top() -> tuple[str, ...]:
        # The title block sits at depth 0; the first heading below it (a numbered
        # clause or an exhibit) is the top-level section. Before any, the title
        # block itself (the preamble) is the section.
        for n, heading in enumerate(stack):
            if heading.depth >= 1:
                return path()[: n + 1]
        return path()

    def start(kind: str) -> _Segment:
        segment = _Segment(kind, path(), top())
        segments.append(segment)
        return segment

    current: _Segment | None = None
    seen_numbered = False
    for element in elements:
        if element.kind == "table":
            start("table").elements.append(element)
            current = None
            continue

        heading = _heading_for(element.text, stack, element.kind == "heading", seen_numbered)
        if heading:
            seen_numbered = seen_numbered or heading.numbered
            _push(stack, heading)
            # Consecutive headings with no body between them (a title block, or
            # "ARTICLE 5" followed by "5.1 Fees") travel with the next clause.
            carried = current.elements if current and all(e.kind == "heading" for e in current.elements) else []
            if carried:
                segments.remove(current)
            current = start("text")
            current.elements.extend([*carried, element])
            continue

        if is_definition(element.text):
            start("definition").elements.append(element)
            current = None
            continue

        if current is None or current.kind != "text":
            current = start("text")
        current.elements.append(element)
    return [s for s in segments if s.elements]


# ---------------------------------------------------------------- sizing


def _section(path: tuple[str, ...]) -> str | None:
    return path[-1] if path else None


def _merge_small(segments: list[_Segment], min_tokens: int, max_tokens: int) -> list[list[_Segment]]:
    """Group consecutive short clauses of the same kind and parent."""
    groups: list[list[_Segment]] = []
    for segment in segments:
        if groups:
            last = groups[-1]
            head = last[0]
            size = sum(_tokens(s) for s in last)
            if (
                segment.kind == head.kind != "table"
                and segment.path[:-1] == head.path[:-1]
                and size < min_tokens
                and size + _tokens(segment) <= max_tokens
            ):
                last.append(segment)
                continue
        groups.append([segment])
    return groups


def _tokens(segment: _Segment) -> int:
    return sum(count_tokens(e.text) for e in segment.elements)


def _split_text(text: str, max_tokens: int) -> list[str]:
    """Split one oversized paragraph at sentence ends, with one sentence of overlap."""
    sentences: list[str] = []
    for sentence in _SENTENCE_END_RE.split(text):
        while (tokens := count_tokens(sentence)) > max_tokens:  # a runaway "sentence"
            cut = len(sentence) * max_tokens // tokens
            sentences.append(sentence[:cut])
            sentence = sentence[cut:]
        sentences.append(sentence)

    pieces: list[list[str]] = []
    current: list[str] = []
    for sentence in sentences:
        if current and count_tokens(" ".join([*current, sentence])) > max_tokens:
            pieces.append(current)
            overlap = current[-1]
            current = [overlap] if len(current) > 1 and count_tokens(f"{overlap} {sentence}") <= max_tokens else []
        current.append(sentence)
    if current:
        pieces.append(current)
    return [" ".join(p) for p in pieces]


def _split_table(text: str, max_tokens: int) -> list[str]:
    lines = text.splitlines()
    header_end = next((i + 1 for i, line in enumerate(lines) if re.match(r"^\|?\s*:?-{3,}", line)), 0)
    header, rows = lines[:header_end], lines[header_end:]
    pieces: list[list[str]] = [[]]
    for row in rows:
        if pieces[-1] and count_tokens("\n".join(header + pieces[-1] + [row])) > max_tokens:
            pieces.append([])
        pieces[-1].append(row)
    return ["\n".join(header + p) for p in pieces if p]


def _pack(elements: list[Element], max_tokens: int, kind: str) -> list[list[Element]]:
    """Pack whole elements into pieces under max_tokens, splitting only oversized ones."""
    pieces: list[list[Element]] = [[]]
    size = 0
    for element in elements:
        tokens = count_tokens(element.text)
        if tokens > max_tokens:
            parts = _split_table(element.text, max_tokens) if kind == "table" else _split_text(element.text, max_tokens)
            for part in parts:
                pieces.append([_replace_text(element, part)])
            pieces.append([])
            size = 0
            continue
        if pieces[-1] and size + tokens > max_tokens:
            pieces.append([])
            size = 0
        pieces[-1].append(element)
        size += tokens
    return [p for p in pieces if p]


def _replace_text(element: Element, text: str) -> Element:
    return Element(element.kind, text, element.page_start, element.page_end, element.bboxes, element.source)


# ---------------------------------------------------------------- entry point


def chunk_document(elements: list[Element], title: str) -> list[ChunkDraft]:
    settings = get_settings()
    min_tokens, max_tokens = settings.chunk_min_tokens, settings.chunk_max_tokens

    drafts: list[ChunkDraft] = []
    for group in _merge_small(_segments(elements), min_tokens, max_tokens):
        sections = list(dict.fromkeys(s for s in (_section(seg.path) for seg in group) if s))
        if len(sections) > 1:
            section = _short(f"{sections[0]} – {sections[-1]}")
            path = group[0].path[:-1] + (section,)
        else:
            section = sections[0] if sections else None
            path = group[0].path
        # Merged top-level clauses ("5. Fees – 6. Taxes") form their own section.
        tops = {seg.top for seg in group}
        section_path = group[0].top if len(tops) == 1 else path

        all_elements = [e for seg in group for e in seg.elements]
        for piece in _pack(all_elements, max_tokens, group[0].kind):
            content = "\n".join(e.text for e in piece)
            heading_path = " > ".join(path) or None
            pages = [p for e in piece for p in (e.page_start, e.page_end) if p is not None]
            drafts.append(
                ChunkDraft(
                    content=content,
                    embed_text="\n".join(filter(None, [" > ".join((title, *path)), content])),
                    heading_path=heading_path,
                    section=section,
                    element_type=group[0].kind,
                    source="ocr" if any(e.source == "ocr" for e in piece) else "text_layer",
                    page_start=min(pages) if pages else None,
                    page_end=max(pages) if pages else None,
                    bboxes=[b for e in piece for b in e.bboxes],
                    token_count=count_tokens(content),
                    section_path=section_path,
                )
            )
    return drafts


def build_sections(drafts: list[ChunkDraft], title: str) -> list[SectionDraft]:
    """Consecutive chunks with the same section_path, with the text to embed:
    breadcrumb plus the section's content, cut at `section_embed_max_tokens`
    (the embedding server's context; LM Studio silently truncates past it)."""
    max_tokens = get_settings().section_embed_max_tokens
    sections: list[SectionDraft] = []
    current_path: tuple[str, ...] | None = None
    for i, draft in enumerate(drafts):
        if not sections or draft.section_path != current_path:
            current_path = draft.section_path
            sections.append(SectionDraft(" > ".join(current_path) or None, [], "", 0))
        sections[-1].chunk_indexes.append(i)
        sections[-1].token_count += draft.token_count

    for section in sections:
        breadcrumb = " > ".join(filter(None, [title, section.heading_path]))
        content = "\n".join(drafts[i].content for i in section.chunk_indexes)
        section.embed_text = _truncate_tokens(f"{breadcrumb}\n{content}", max_tokens)
    return sections


def _truncate_tokens(text: str, max_tokens: int) -> str:
    tokenizer = _tokenizer()
    if tokenizer is None:
        return text[: max_tokens * 4]
    encoding = tokenizer.encode(text, add_special_tokens=False)
    if len(encoding.ids) <= max_tokens:
        return text
    return text[: encoding.offsets[max_tokens - 1][1]]
