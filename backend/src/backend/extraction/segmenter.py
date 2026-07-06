"""Clause-level segmentation with provenance (design doc §3.2, §3.4).

Detects numbered legal headings ("8. LIABILITY", "2.1 Sublease") and slices
the document into sections with stable ids and character offsets into the
full text, plus the page each section starts on. Clause-level chunks keep
legal context intact and are the unit for citations and template diffing.
"""

import re
from dataclasses import dataclass

from backend.extraction.fast_path import Page

# Numbered heading on its own line: "3. TERM", "10. GOVERNING LAW", "2.1 X".
# Title must be mostly uppercase to avoid matching numbered list items.
_HEADING = re.compile(
    r"^[ \t]*(\d+(?:\.\d+)*)[.)]?[ \t]+([A-Z][A-Z0-9 /&'-]{2,})[ \t]*$", re.MULTILINE
)


@dataclass
class Section:
    section_id: str      # e.g. "sec-8"
    number: str          # e.g. "8"
    heading: str         # e.g. "8. LIABILITY"
    start: int           # char offset into full_text (heading start)
    end: int             # char offset (exclusive)
    page: int            # page the section starts on


def join_pages(pages: list[Page]) -> tuple[str, list[int]]:
    """Concatenate pages; return (full_text, start offset of each page)."""
    offsets: list[int] = []
    parts: list[str] = []
    pos = 0
    for page in pages:
        offsets.append(pos)
        parts.append(page.text)
        pos += len(page.text) + 1  # +1 for the joining newline
    return "\n".join(parts), offsets


def _page_of(offset: int, page_offsets: list[int]) -> int:
    page = 1
    for i, start in enumerate(page_offsets):
        if offset >= start:
            page = i + 1
    return page


def segment(pages: list[Page]) -> tuple[str, list[Section]]:
    """Return (full_text, sections). Text before the first heading (title,
    preamble) is section 'sec-0'."""
    full_text, page_offsets = join_pages(pages)
    matches = list(_HEADING.finditer(full_text))
    sections: list[Section] = []

    if not matches:
        if full_text.strip():
            sections.append(Section("sec-0", "0", "PREAMBLE", 0, len(full_text), 1))
        return full_text, sections

    if matches[0].start() > 0 and full_text[: matches[0].start()].strip():
        sections.append(
            Section("sec-0", "0", "PREAMBLE", 0, matches[0].start(),
                    _page_of(0, page_offsets))
        )
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        number = m.group(1)
        sections.append(
            Section(
                section_id=f"sec-{number.replace('.', '-')}",
                number=number,
                heading=f"{number}. {m.group(2).strip()}",
                start=m.start(),
                end=end,
                page=_page_of(m.start(), page_offsets),
            )
        )
    return full_text, sections
