"""PlayQuiz reads use the same actor and RLS as the notebook workspace."""
from __future__ import annotations

from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection


async def profile(engine: AsyncEngine, actor: ActorContext) -> dict[str, Any]:
    async with actor_connection(engine, actor.actor_id) as conn:
        row = (await conn.execute(text("SELECT id, display_name, email FROM users WHERE id=:id"), {"id": actor.actor_id})).mappings().one()
    return {"id": str(row["id"]), "display_name": row["display_name"], "email": row["email"]}


async def quiz_catalog(engine: AsyncEngine, actor: ActorContext, page: int = 1) -> dict[str, Any]:
    async with actor_connection(engine, actor.actor_id) as conn:
        rows = (await conn.execute(text("""
            SELECT q.id, q.notebook_id, q.title, q.difficulty,
                   ARRAY(SELECT DISTINCT x.question_type FROM quiz_questions x
                         WHERE x.quiz_id=q.id ORDER BY x.question_type) AS question_types,
                   q.created_at, n.title AS notebook_title,
                   (SELECT count(*) FROM quiz_questions x WHERE x.quiz_id=q.id) AS question_count,
                   count(*) OVER () AS total
            FROM quizzes q JOIN digital_notebooks n ON n.id=q.notebook_id
            WHERE q.created_by=:actor AND q.status='ready' AND n.status='active'
              AND EXISTS (SELECT 1 FROM quiz_questions x WHERE x.quiz_id=q.id)
              AND NOT EXISTS (SELECT 1 FROM quiz_questions x WHERE x.quiz_id=q.id
                              AND x.question_type NOT IN ('multiple_choice','multiple_select'))
            ORDER BY q.created_at DESC, q.id
            LIMIT 100 OFFSET :offset
        """), {"actor": actor.actor_id, "offset": (page - 1) * 100})).mappings().all()
    return {"items": [{k: str(v) if k in ("id", "notebook_id", "created_at") else v for k, v in r.items() if k != "total"} for r in rows],
            "page": page, "has_next": bool(rows and page * 100 < rows[0]["total"])}
