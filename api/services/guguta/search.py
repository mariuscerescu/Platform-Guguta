"""Retrieval over an authorized notebook scope (GHID §7.1).

The authorized set is fixed BEFORE retrieval: only chunks belonging to the
notebook's selected sources can reach the query or the model. Text search
uses normalized Romanian stemming; vector search uses
cosine distance in the active embedding space with a configured cutoff.
Combination is an interleaved merge — reranking comes later, measured.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.ai.guguta.openrouter import invoke
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import OpenNotebookError

_TOKEN_RE = re.compile(r"[a-z0-9ăâîșțşţ]+", re.IGNORECASE)
_ROMANIAN_FOLD = str.maketrans("ăâîșşțţ", "aaisstt")
# Retrieval instructions and common function words are not the subject being
# sought. Grammatical inflection is handled by PostgreSQL's built-in Romanian
# dictionary. Neither this set nor the dictionary contains benchmark questions,
# page numbers or expected answers.
_QUERY_STOP_WORDS = frozenset({
    "gaseste", "gasiti", "reda", "redati", "citeaza", "citati",
    "manual", "manualul", "manualului", "raspunde", "concis", "explica",
    "scurt", "problema", "problemele", "exercitiul", "exercitiului",
    "exercitiile", "datele", "intrebarea", "rezolvare", "rezolva",
    "si", "in", "din", "de", "la", "cu", "pe", "care", "pentru", "despre",
    "fara", "o", "un", "a", "ce", "se", "sa", "al", "ale", "ai", "este",
    "sunt", "iar", "ca", "cum", "daca", "intr", "unei", "unui",
})
_PAGE_RE = re.compile(
    r"\b(?:pagina|pagin[ăa]|pag\.?)\s*(?:(pdf|tip[ăa]rit[ăa])\s*)?(\d{1,5})\b",
    re.IGNORECASE,
)


def requested_page(query: str) -> tuple[str, int] | None:
    """Resolve explicit Romanian page references, never guess a PDF offset.

    Printed and PDF pages are distinct metadata fields. An unspecified page
    means the page printed in the book, as in ordinary classroom requests.
    """
    match = _PAGE_RE.search(query)
    if not match:
        return None
    return ("page" if (match[1] or "").casefold() == "pdf" else "printed_page", int(match[2]))


def _interleave_ids(text_ids: list[uuid.UUID], vector_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Keep candidates from both retrieval channels regardless of score units.

    An OR text query frequently fills the whole candidate budget; placing all
    text hits first would silently discard every semantic/vector candidate.
    """
    merged = []
    seen = set()
    for rank in range(max(len(text_ids),len(vector_ids))):
        for channel in (text_ids,vector_ids):
            if rank < len(channel) and channel[rank] not in seen:
                seen.add(channel[rank])
                merged.append(channel[rank])
    return merged


def _diverse_pages(chunks: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
    """Prefer complementary PDF pages over duplicate native/OCR chunks.

    Retain secondary chunks when fewer distinct pages exist than the requested
    limit. Text-only materials retain ordinary per-chunk ranking.
    """
    primary,secondary,seen = [],[],set()
    for chunk in chunks:
        page = chunk.locator.get("page")
        key = (chunk.material_version_id,page) if page is not None else chunk.chunk_id
        if key in seen:
            secondary.append(chunk)
        else:
            seen.add(key)
            primary.append(chunk)
    return (primary+secondary)[:limit]


def _or_tsquery(query: str) -> str:
    """Build an OR tsquery from sanitized tokens (recall-oriented ranking).

    Tokens are allowlisted (letters/digits), so no SQL/tsquery injection.
    """
    tokens = [t.lower().translate(_ROMANIAN_FOLD) for t in _TOKEN_RE.findall(query)]
    if not tokens:
        return ""
    meaningful = [t for t in tokens if t not in _QUERY_STOP_WORDS]
    return " | ".join(dict.fromkeys(meaningful or tokens))


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    text: str
    locator: dict[str, Any]
    notebook_source_id: uuid.UUID
    material_version_id: uuid.UUID
    local_name: str
    score: float
    mode: str = "text"
    image_url: str | None = field(default=None, repr=False, compare=False)
    extracted_text: str | None = field(default=None, repr=False, compare=False)


class SearchService:
    def __init__(
        self, engine: AsyncEngine, vector_provider: Any, *,
        max_vector_distance: float = 0.9,
        reranker: Any = None, candidate_limit: int = 24,
    ) -> None:
        self._reranker = reranker
        self._candidate_limit = candidate_limit
        self._engine = engine
        self._provider = vector_provider
        self._max_vector_distance = max_vector_distance

    async def search_notebook(
        self, actor_id: uuid.UUID, notebook_id: uuid.UUID, query: str, *,
        mode: str = "both", limit: int = 8,
    ) -> list[RetrievedChunk]:
        """Search a notebook with one query (compatibility wrapper)."""
        return await self.search_notebook_multi(
            actor_id, notebook_id, [query], query, mode=mode, limit=limit,
        )

    async def search_notebook_multi(
        self, actor_id: uuid.UUID, notebook_id: uuid.UUID,
        queries: list[str], ranking_query: str, *,
        mode: str = "both", limit: int = 8,
    ) -> list[RetrievedChunk]:
        """Retrieve for several perspectives, fuse, then rerank once.

        Authorization is established before any provider call. Embeddings are
        batched and reranking sees only original, authorized chunk objects.
        Reciprocal-rank fusion prevents one broad sub-query from crowding out
        evidence found by the other perspectives.
        """
        clean_queries: list[str] = []
        seen_queries: set[str] = set()
        for query in queries[:4]:
            normalized = " ".join((query or "").split()).strip()
            key = normalized.casefold()
            if normalized and key not in seen_queries:
                clean_queries.append(normalized[:1000])
                seen_queries.add(key)
        if not clean_queries:
            return []
        limit = max(1, min(limit, 50))
        page_request = requested_page(ranking_query)
        if page_request is not None:
            # A page constraint is authoritative, not another semantic hint.
            # Do not rerank it away or silently substitute a different page.
            return await self._search_page(actor_id, notebook_id, page_request, limit)
        candidate_limit = max(limit, self._candidate_limit) if self._reranker else limit
        async with actor_connection(self._engine, actor_id) as conn:
            nb = (await conn.execute(text("SELECT id FROM digital_notebooks WHERE id=:id"),
                                     {"id": notebook_id})).first()
            if nb is None:
                from open_notebook.exceptions import NotFoundError
                raise NotFoundError()
            space = (await conn.execute(text(
                "SELECT id, model_name, model_revision, dimension FROM embedding_spaces WHERE is_active"
            ))).mappings().first()
        qvecs: list[Optional[list[float]]] = [None] * len(clean_queries)
        space_id = None
        if mode in ("vector", "both") and space is not None:
            if (space["model_name"] != self._provider.model_name
                or space["model_revision"] != self._provider.model_revision
                or int(space["dimension"]) != self._provider.dimension):
                raise OpenNotebookError("Providerul de embedding nu corespunde spațiului vectorial activ; reindexare necesară.")
            space_id = space["id"]
            # Instruction-aware models distinguish retrieval queries from
            # corpus documents. Legacy providers keep the plain embed method.
            embed_queries = getattr(self._provider, "embed_queries", self._provider.embed)
            qvecs = list(await invoke(embed_queries, clean_queries))
        ranked_lists: list[list[RetrievedChunk]] = []
        async with actor_connection(self._engine, actor_id) as conn:
            for query, qvec in zip(clean_queries, qvecs):
                ranked_lists.append(await self._search_on_conn(
                    conn, actor_id, notebook_id, query,
                    mode=mode, limit=candidate_limit, results={},
                    qvec=qvec, space_id=space_id,
                ))

        by_id: dict[uuid.UUID, RetrievedChunk] = {}
        fusion: dict[uuid.UUID, float] = {}
        for found in ranked_lists:
            for rank, chunk in enumerate(found):
                by_id.setdefault(chunk.chunk_id, chunk)
                fusion[chunk.chunk_id] = fusion.get(chunk.chunk_id, 0.0) + 1.0 / (60 + rank)
        fused = [
            by_id[chunk_id] for chunk_id, _ in sorted(
                fusion.items(), key=lambda item: item[1], reverse=True
            )[:candidate_limit]
        ]
        if self._reranker is not None:
            ranked = await self._reranker.rank(ranking_query, fused, len(fused))
            return _diverse_pages(ranked,limit)
        return _diverse_pages(fused,limit)

    async def _search_page(
        self, actor_id: uuid.UUID, notebook_id: uuid.UUID,
        page_request: tuple[str, int], limit: int,
    ) -> list[RetrievedChunk]:
        field_name, page_number = page_request
        async with actor_connection(self._engine, actor_id) as conn:
            nb = (await conn.execute(text("SELECT id FROM digital_notebooks WHERE id=:nb"),
                                     {"nb":notebook_id})).first()
            if nb is None:
                from open_notebook.exceptions import NotFoundError
                raise NotFoundError()
            rows = (await conn.execute(text(
                "SELECT c.id,c.text,c.locator,ns.id AS ns_id,mv.id AS mv_id,ns.local_name "
                "FROM chunks c JOIN processing_artifacts pa ON pa.id=c.artifact_id "
                "JOIN material_versions mv ON mv.id=pa.material_version_id "
                "JOIN notebook_sources ns ON ns.material_version_id=mv.id "
                "WHERE ns.notebook_id=:nb AND ns.selected_for_chat AND ns.status='ready' "
                "AND pa.status='complete' AND c.locator->>:field_name=:page_number "
                "ORDER BY ns.position,c.position LIMIT :lim"
            ), {"nb":notebook_id,"field_name":field_name,"page_number":str(page_number),
                "lim":limit})).mappings().all()
        return [RetrievedChunk(chunk_id=r["id"],text=r["text"],locator=dict(r["locator"] or {}),
                               notebook_source_id=r["ns_id"],material_version_id=r["mv_id"],
                               local_name=r["local_name"],score=1.0,mode="locator") for r in rows]

    async def _search_on_conn(
        self, conn: Any, actor_id: uuid.UUID, notebook_id: uuid.UUID,
        query: str, *, mode: str, limit: int,
        results: dict[uuid.UUID, RetrievedChunk],
        qvec: Optional[list[float]] = None, space_id: Any = None,
    ) -> list[RetrievedChunk]:
        # Foreign notebooks return 404 rather than an empty result set.
        nb = (
            await conn.execute(
                text("SELECT id FROM digital_notebooks WHERE id = :id"),
                {"id": notebook_id},
            )
        ).first()
        if nb is None:
            from open_notebook.exceptions import NotFoundError

            raise NotFoundError()
        tsq = _or_tsquery(query)
        text_ids: list[uuid.UUID] = []
        vector_ids: list[uuid.UUID] = []
        if mode in ("text", "both"):
            rows = (
                await conn.execute(
                    text(
                        "SELECT c.id, c.text, c.locator, ns.id AS ns_id,"
                        " mv.id AS mv_id, ns.local_name,"
                        " ts_rank(to_tsvector('romanian', translate(lower(c.text),'ăâîșşțţ','aaisstt')),"
                        "         to_tsquery('romanian', :tsq)) AS rank"
                        " FROM chunks c"
                        " JOIN processing_artifacts pa ON pa.id = c.artifact_id"
                        " JOIN material_versions mv ON mv.id = pa.material_version_id"
                        " JOIN notebook_sources ns ON ns.material_version_id = mv.id"
                        " JOIN digital_notebooks dn ON dn.id = ns.notebook_id"
                        " WHERE dn.id = :nb AND ns.selected_for_chat AND ns.status = 'ready'"
                        "   AND (c.text ILIKE :like"
                        "        OR (CAST(:tsq AS text) <> ''"
                        "           AND to_tsvector('romanian', translate(lower(c.text),'ăâîșşțţ','aaisstt'))"
                        "           @@ to_tsquery('romanian', :tsq)))"
                        " ORDER BY rank DESC, ns.position, c.position"
                        " LIMIT :lim"
                    ),
                    {"tsq": tsq, "like": f"%{query.strip()}%",
                     "nb": notebook_id, "lim": limit},
                )
            ).mappings().all()
            for r in rows:
                text_ids.append(r["id"])
                results[r["id"]] = RetrievedChunk(
                    chunk_id=r["id"], text=r["text"],
                    locator=dict(r["locator"] or {}),
                    notebook_source_id=r["ns_id"],
                    material_version_id=r["mv_id"],
                    local_name=r["local_name"], score=float(r["rank"]),
                    mode="text",
                )

        if mode in ("vector", "both"):
            if qvec is not None:
                vrows = (
                    await conn.execute(
                        text(
                            "SELECT c.id, c.text, c.locator, ns.id AS ns_id,"
                            " mv.id AS mv_id, ns.local_name,"
                            " e.embedding <=> CAST(:qv AS vector) AS dist"
                            " FROM embeddings e"
                            " JOIN chunks c ON c.id = e.chunk_id"
                            " JOIN embedding_spaces es ON es.id = e.embedding_space_id"
                            " JOIN processing_artifacts pa ON pa.id = c.artifact_id"
                            " JOIN material_versions mv ON mv.id = pa.material_version_id"
                            " JOIN notebook_sources ns ON ns.material_version_id = mv.id"
                            " JOIN digital_notebooks dn ON dn.id = ns.notebook_id"
                            " WHERE dn.id = :nb AND ns.selected_for_chat AND ns.status = 'ready' AND es.is_active AND es.id = :space_id"
                            "   AND e.embedding <=> CAST(:qv AS vector)"
                            "       <= CAST(:maxd AS float8)"
                            " ORDER BY e.embedding <=> CAST(:qv AS vector)"
                            " LIMIT :lim"
                        ),
                        {"qv": str(qvec), "nb": notebook_id, "lim": limit,
                         "maxd": self._max_vector_distance, "space_id": space_id},
                    )
                ).mappings().all()
                for r in vrows:
                    vector_ids.append(r["id"])
                    if r["id"] in results:
                        continue
                    results[r["id"]] = RetrievedChunk(
                        chunk_id=r["id"], text=r["text"],
                        locator=dict(r["locator"] or {}),
                        notebook_source_id=r["ns_id"],
                        material_version_id=r["mv_id"],
                        local_name=r["local_name"],
                        score=float(r["dist"]), mode="vector",
                    )

        # Channel ranks already have the right direction (ts_rank descending,
        # distance ascending). Interleave ranks, never compare their raw units.
        return [results[key] for key in _interleave_ids(text_ids,vector_ids)[:limit]]
