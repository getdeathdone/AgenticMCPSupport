"""Markdown knowledge base retrieval for RAG-style support answers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = ROOT / "knowledge_base"
FUZZY_THRESHOLD = 0.78


@dataclass(frozen=True)
class KnowledgeChunk:
    """A searchable chunk from a markdown knowledge document."""

    title: str
    source: str
    content: str
    terms: set[str]


def search_knowledge_base(query: str) -> KnowledgeChunk | None:
    """Return the best matching markdown knowledge chunk for a query."""

    query_terms = _tokenize(query)
    if not query_terms:
        return None

    best_chunk: KnowledgeChunk | None = None
    best_score = 0
    for chunk in _load_chunks():
        score = _score(query_terms, chunk.terms)
        if score > best_score:
            best_score = score
            best_chunk = chunk

    return best_chunk if best_score > 0 else None


def _load_chunks() -> list[KnowledgeChunk]:
    """Load markdown docs and split them into heading-based chunks."""

    chunks: list[KnowledgeChunk] = []
    if not KNOWLEDGE_BASE_DIR.exists():
        return chunks

    for path in sorted(KNOWLEDGE_BASE_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = _extract_title(text, path)
        sections = _split_sections(text)
        for heading, content in sections:
            chunk_title = f"{title}: {heading}" if heading else title
            searchable = f"{chunk_title}\n{content}"
            chunks.append(
                KnowledgeChunk(
                    title=chunk_title,
                    source=str(path.relative_to(ROOT)).replace("\\", "/"),
                    content=_normalize_content(content),
                    terms=_tokenize(searchable),
                )
            )
    return chunks


def _extract_title(text: str, path: Path) -> str:
    """Extract the first markdown H1 or fall back to the filename."""

    match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else path.stem.replace("_", " ").title()


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into H2 sections."""

    matches = list(re.finditer(r"^##\s+(.+)$", text, flags=re.MULTILINE))
    if not matches:
        return [("", re.sub(r"^#\s+.+$", "", text, flags=re.MULTILINE).strip())]

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1).strip(), text[start:end].strip()))
    return sections


def _normalize_content(content: str) -> str:
    """Normalize markdown content into compact plain text."""

    return re.sub(r"\s+", " ", content.replace("#", "")).strip()


def _tokenize(text: str) -> set[str]:
    """Tokenize text for fuzzy keyword retrieval."""

    return {term for term in re.findall(r"[a-z0-9-]+", text.lower()) if len(term) > 2}


def _score(query_terms: set[str], candidate_terms: set[str]) -> int:
    """Score a candidate chunk with exact and fuzzy term matches."""

    exact_score = len(query_terms.intersection(candidate_terms)) * 2
    fuzzy_score = sum(
        1
        for query_term in query_terms
        if any(_is_fuzzy_match(query_term, candidate_term) for candidate_term in candidate_terms)
    )
    return exact_score + fuzzy_score


def _is_fuzzy_match(left: str, right: str) -> bool:
    """Return whether two terms are similar enough for retrieval."""

    if left == right or left in right or right in left:
        return True
    return SequenceMatcher(None, left, right).ratio() >= FUZZY_THRESHOLD
