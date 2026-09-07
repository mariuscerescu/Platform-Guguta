"""Retrieval over an authorized notebook scope (GHID §7.1).

The authorized set is fixed BEFORE retrieval: only chunks belonging to the
notebook's selected sources can reach the query or the model. Text search
uses simple normalization (ILIKE + tsvector 'simple'); vector search uses
cosine distance in the active embedding space with a configured cutoff.
Combination is an interleaved merge — reranking comes later, measured.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.ai.guguta.openrouter import invoke
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import OpenNotebookError

_TOKEN_RE = re.compile(r"[a-z0-9ăâîșțşţ]+", re.IGNORECASE)


def _or_tsquery(query: str) -> str:
    """Build an OR tsquery from sanitized tokens (recall-oriented ranking).

    Tokens are allowlisted (letters/digits), so no SQL/tsquery injection.
    """
    tokens = _TOKEN_RE.findall(query)
    if not tokens:
        return ""
    return " | ".join(t.lower() for t in tokens)


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
        """Authorize first; all embedding/reranking HTTP runs outside SQL transactions."""
        if not query or not query.strip():
            return []
        limit = max(1, min(limit, 50))
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
        qvec = None
        space_id = None
        if mode in ("vector", "both") and space is not None:
            if (space["model_name"] != self._provider.model_name
                or space["model_revision"] != self._provider.model_revision
                or int(space["dimension"]) != self._provider.dimension):
                raise OpenNotebookError("Providerul de embedding nu corespunde spațiului vectorial activ; reindexare necesară.")
            space_id = space["id"]
            qvec = (await invoke(self._provider.embed, [query.strip()]))[0]
        async with actor_connection(self._engine, actor_id) as conn:
            found = await self._search_on_conn(conn, actor_id, notebook_id, query,
                mode=mode, limit=candidate_limit, results={}, qvec=qvec, space_id=space_id)
        if self._reranker is not None:
            return await self._reranker.rank(query, found, limit)
        return found[:limit]

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
        if mode in ("text", "both"):
            rows = (
                await conn.execute(
                    text(
                        "SELECT c.id, c.text, c.locator, ns.id AS ns_id,"
                        " mv.id AS mv_id, ns.local_name,"
                        " ts_rank(to_tsvector('simple', c.text),"
                        "         to_tsquery('simple', :tsq)) AS rank"
                        " FROM chunks c"
                        " JOIN processing_artifacts pa ON pa.id = c.artifact_id"
                        " JOIN material_versions mv ON mv.id = pa.material_version_id"
                        " JOIN notebook_sources ns ON ns.material_version_id = mv.id"
                        " JOIN digital_notebooks dn ON dn.id = ns.notebook_id"
                        " WHERE dn.id = :nb AND ns.selected_for_chat AND ns.status = 'ready'"
                        "   AND (c.text ILIKE :like"
                        "        OR (CAST(:tsq AS text) <> ''"
                        "           AND to_tsvector('simple', c.text)"
                        "           @@ to_tsquery('simple', :tsq)))"
                        " ORDER BY rank DESC, ns.position, c.position"
                        " LIMIT :lim"
                    ),
                    {"tsq": tsq, "like": f"%{query.strip()}%",
                     "nb": notebook_id, "lim": limit},
                )
            ).mappings().all()
            for r in rows:
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

        # F16: text score = ts_rank (higher better); vector score = cosine
        # distance (lower better). Normalize before merging.
        def _relevance(c: RetrievedChunk) -> float:
            return c.score if c.mode == "text" else -c.score

        ordered = sorted(
            results.values(),
            key=lambda c: (0 if c.mode == "text" else 1, -_relevance(c)),
        )
        return ordered[:limit]
