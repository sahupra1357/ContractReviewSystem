"""Clause-level chunking of MASKED artifacts (design §3.4).

One section = one chunk (legal context intact); oversized sections split on
paragraph boundaries. Chunk identity is the content hash — the key for the
embedding cache.
"""

import hashlib
from dataclasses import dataclass

MAX_CHUNK_CHARS = 4000


@dataclass
class ChunkData:
    section_id: str
    part: int
    heading: str
    text: str
    sha256: str
    start: int
    end: int


def _make(section: dict, part: int, text: str, start: int, end: int) -> ChunkData:
    return ChunkData(
        section_id=section["section_id"],
        part=part,
        heading=section["heading"],
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        start=start,
        end=end,
    )


def chunk_masked_artifact(masked_artifact: dict) -> list[ChunkData]:
    text = masked_artifact["masked_text"]
    chunks: list[ChunkData] = []
    for section in masked_artifact["sections"]:
        s_text = text[section["start"]:section["end"]].strip()
        if not s_text:
            continue
        if len(s_text) <= MAX_CHUNK_CHARS:
            chunks.append(_make(section, 0, s_text, section["start"], section["end"]))
            continue
        # split long sections on blank lines, packing parts up to the limit
        part, buf, buf_start, pos = 0, "", section["start"], section["start"]
        for para in s_text.split("\n\n"):
            candidate = f"{buf}\n\n{para}" if buf else para
            if buf and len(candidate) > MAX_CHUNK_CHARS:
                chunks.append(_make(section, part, buf, buf_start, pos))
                part, buf, buf_start = part + 1, para, pos
            else:
                buf = candidate
            pos = buf_start + len(buf)
        if buf:
            chunks.append(_make(section, part, buf, buf_start, section["end"]))
    return chunks
