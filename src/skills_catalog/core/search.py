"""Lexical search over skill names and descriptions (SQLite FTS5, BM25 ranking).

The assistant does the semantic work of turning a need into keywords; the catalog only needs a
cheap, deterministic index. Raw user text is never passed to FTS5, whose query syntax would
choke on quotes, hyphens, colons or operators.
"""

from __future__ import annotations

import re
import sqlite3

from .models import SearchResult

DEFAULT_LIMIT = 5
MAX_LIMIT = 20
_WORD = re.compile(r"\w+")

# Function words and conversational filler. With OR semantics, a single "the" or "our" matches
# almost every description, so a sentence passed verbatim would never return "no match". Found by
# the discovery eval (tests/eval): with sentences passed verbatim, "no match" was never returned;
# dropping these fixes that for needs that share only function words with the catalog.
STOPWORDS = frozenset(
    """
    a about after all also am an and any are as at be been before but by can could did do does
    for from had has have help how i if in into is it its just me my need no not of on or our
    please should so some than that the their them then there these they this those to too us
    was we were what when where which while who why will with would you your want
    """.split()  # noqa: SIM905 - a word block reads better than 80 quoted strings
)


def to_fts_query(query: str) -> str:
    """Turn free text into an FTS5 query: content words quoted as literals, OR-ed together."""
    tokens = dict.fromkeys(t for t in _WORD.findall(query.lower()) if t not in STOPWORDS)
    return " OR ".join(f'"{t}"' for t in tokens)


def search(conn: sqlite3.Connection, query: str, limit: int = DEFAULT_LIMIT) -> list[SearchResult]:
    fts_query = to_fts_query(query)
    if not fts_query:
        return []
    limit = max(1, min(limit, MAX_LIMIT))
    rows = conn.execute(
        """
        SELECT f.name, f.description,
               (SELECT max(v.version) FROM versions v WHERE v.name = f.name) AS latest_version
        FROM skills_fts AS f
        WHERE skills_fts MATCH ?
        ORDER BY bm25(skills_fts)
        LIMIT ?
        """,
        (fts_query, limit),
    ).fetchall()
    return [SearchResult(r["name"], r["description"], r["latest_version"]) for r in rows]
