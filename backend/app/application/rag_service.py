"""RAG retrieval service — three-layer retrieval for business context injection.

Layer 1: DataSource-level — select most relevant data sources by keyword match
Layer 2: Table-level — select most relevant tables by keyword + edit distance
Layer 3: Knowledge-level — match example SQL and terminology

Pure Python implementation — TF-IDF + keyword matching + edit distance.
No vector database or heavy dependencies.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

from app.infrastructure.persistence import context_store

logger = logging.getLogger("chatsql")


# ── Text Processing Utilities ──


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens. Handles CJK characters individually."""
    # Split on non-alphanumeric, keep CJK chars as individual tokens
    tokens = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9_]+', text.lower())
    return tokens


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text, removing common stop words."""
    stop_words = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
        "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "and", "but", "or",
        "not", "no", "nor", "so", "yet", "both", "either", "neither",
        "each", "every", "all", "any", "few", "more", "most", "other",
        "some", "such", "than", "too", "very", "just", "about",
    }
    tokens = _tokenize(text)
    return {t for t in tokens if t not in stop_words and len(t) > 1}


def _edit_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(
                curr_row[j] + 1,       # insert
                prev_row[j + 1] + 1,   # delete
                prev_row[j] + cost,    # replace
            ))
        prev_row = curr_row
    return prev_row[-1]


def _keyword_match_score(keywords: set[str], target_text: str) -> float:
    """Score how well keywords match target text. Returns 0-1."""
    if not keywords:
        return 0.0
    target_tokens = set(_tokenize(target_text.lower()))
    if not target_tokens:
        return 0.0

    # Exact matches
    exact_hits = keywords & target_tokens

    # Fuzzy matches (edit distance <= 1 for tokens >= 3 chars)
    fuzzy_hits = set()
    for kw in keywords:
        if kw in exact_hits:
            continue
        if len(kw) < 3:
            continue
        for tt in target_tokens:
            if len(tt) < 3:
                continue
            if _edit_distance(kw, tt) <= 1:
                fuzzy_hits.add(kw)
                break

    total_hits = len(exact_hits) + len(fuzzy_hits) * 0.7
    return min(total_hits / len(keywords), 1.0)


def _tfidf_similarity(text1: str, text2: str) -> float:
    """Compute a simple TF-IDF-like cosine similarity between two texts."""
    tokens1 = _tokenize(text1.lower())
    tokens2 = _tokenize(text2.lower())

    if not tokens1 or not tokens2:
        return 0.0

    counter1 = Counter(tokens1)
    counter2 = Counter(tokens2)

    # All unique tokens
    all_tokens = set(counter1.keys()) | set(counter2.keys())

    # Cosine similarity
    dot_product = sum(counter1.get(t, 0) * counter2.get(t, 0) for t in all_tokens)
    norm1 = math.sqrt(sum(v ** 2 for v in counter1.values()))
    norm2 = math.sqrt(sum(v ** 2 for v in counter2.values()))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


# ═══════════════════════════════════════════════════════
# THREE-LAYER RAG RETRIEVAL
# ═══════════════════════════════════════════════════════


async def retrieve_context(
    user_query: str,
    *,
    datasource: str | None = None,
    top_k_tables: int = 5,
    top_k_examples: int = 3,
    top_k_terms: int = 10,
) -> dict[str, Any]:
    """Three-layer RAG retrieval.

    Returns dict with keys: relevant_tables, relevant_relations, relevant_examples, relevant_terms
    """
    keywords = _extract_keywords(user_query)

    # ── Layer 1: DataSource-level (simplified: use provided datasource or all) ──
    # In multi-source mode, score each datasource by table name overlap
    all_tables = await context_store.list_tables_meta(datasource)

    # ── Layer 2: Table-level retrieval ──
    scored_tables: list[tuple[float, dict]] = []
    for t in all_tables:
        if t.get("hidden"):
            continue
        # Build searchable text from table metadata
        search_text = " ".join([
            t.get("name", ""),
            t.get("display_name", ""),
            t.get("description", ""),
            t.get("category", ""),
        ])
        score = _keyword_match_score(keywords, search_text)
        # Bonus for exact table name match
        if t.get("name", "").lower() in {kw.lower() for kw in keywords}:
            score = min(score + 0.3, 1.0)
        if t.get("display_name", "").lower() in {kw.lower() for kw in keywords}:
            score = min(score + 0.3, 1.0)
        scored_tables.append((score, t))

    # Sort by score descending, take top-K
    scored_tables.sort(key=lambda x: x[0], reverse=True)
    relevant_tables = [t for _, t in scored_tables[:top_k_tables]]

    # Also include tables that score > 0 even if beyond top_k
    # (but cap at 2x top_k to avoid bloat)
    if not relevant_tables and scored_tables:
        # Fallback: include top tables even with 0 score if no keyword match
        relevant_tables = [t for _, t in scored_tables[:min(3, len(scored_tables))]]

    # ── Relations: get relations involving relevant tables ──
    all_relations = await context_store.list_relations(datasource)
    relevant_table_names = {t["name"] for t in relevant_tables}
    relevant_relations = [
        r for r in all_relations
        if r.get("source_table") in relevant_table_names
        or r.get("target_table") in relevant_table_names
    ]

    # ── Layer 3: Knowledge-level retrieval ──

    # Examples: match by question similarity
    all_examples = await context_store.list_examples(datasource)
    scored_examples: list[tuple[float, dict]] = []
    for ex in all_examples:
        score = _keyword_match_score(keywords, ex.get("question", ""))
        # Also check TF-IDF similarity
        tfidf_score = _tfidf_similarity(user_query, ex.get("question", ""))
        combined = max(score, tfidf_score)
        scored_examples.append((combined, ex))

    scored_examples.sort(key=lambda x: x[0], reverse=True)
    relevant_examples = [e for _, e in scored_examples[:top_k_examples]]

    # Terminology: match by term name
    all_terms = await context_store.list_terminology()
    scored_terms: list[tuple[float, dict]] = []
    for term in all_terms:
        term_text = term.get("term", "")
        # Direct keyword match
        score = _keyword_match_score(keywords, f"{term_text} {term.get('definition', '')}")
        # Check if term appears in user query
        if term_text.lower() in user_query.lower():
            score = min(score + 0.5, 1.0)
        scored_terms.append((score, term))

    scored_terms.sort(key=lambda x: x[0], reverse=True)
    # Only include terms with some relevance
    relevant_terms = [t for s, t in scored_terms if s > 0][:top_k_terms]
    # If no relevant terms found, include all as fallback context
    if not relevant_terms and all_terms:
        relevant_terms = all_terms[:top_k_terms]

    return {
        "relevant_tables": relevant_tables,
        "relevant_relations": relevant_relations,
        "relevant_examples": relevant_examples,
        "relevant_terms": relevant_terms,
    }


def build_context_prompt(rag_result: dict[str, Any]) -> str:
    """Build a context string from RAG results for injection into system prompt."""
    parts: list[str] = []

    # Tables
    tables = rag_result.get("relevant_tables", [])
    if tables:
        parts.append("## 相关表信息")
        for t in tables:
            name = t.get("name", "")
            display = t.get("display_name", "")
            desc = t.get("description", "")
            header = f"- **{name}**"
            if display:
                header += f" ({display})"
            if desc:
                header += f": {desc}"
            parts.append(header)
            category = t.get("category", "")
            if category:
                parts.append(f"  分类: {category}")
        parts.append("")

    # Relations
    relations = rag_result.get("relevant_relations", [])
    if relations:
        parts.append("## 表关联关系")
        for r in relations:
            src = f"{r.get('source_table', '')}.{r.get('source_column', '')}"
            tgt = f"{r.get('target_table', '')}.{r.get('target_column', '')}"
            join_type = r.get("join_type", "INNER")
            desc = r.get("description", "")
            line = f"- {src} → {tgt} ({join_type} JOIN)"
            if desc:
                line += f" — {desc}"
            parts.append(line)
        parts.append("")

    # Examples
    examples = rag_result.get("relevant_examples", [])
    if examples:
        parts.append("## 参考示例")
        for ex in examples:
            parts.append(f"问题: {ex.get('question', '')}")
            parts.append(f"SQL: {ex.get('sql', '')}")
            if ex.get("description"):
                parts.append(f"说明: {ex['description']}")
            parts.append("")

    # Terminology
    terms = rag_result.get("relevant_terms", [])
    if terms:
        parts.append("## 业务术语")
        for t in terms:
            term = t.get("term", "")
            defn = t.get("definition", "")
            desc = t.get("description", "")
            line = f"- **{term}**: {defn}"
            if desc:
                line += f" ({desc})"
            parts.append(line)
        parts.append("")

    return "\n".join(parts)
