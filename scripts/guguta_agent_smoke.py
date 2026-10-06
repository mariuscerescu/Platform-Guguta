"""Read-only live agent evaluation against an existing authorized chat session.

Uses the deployment's configured model/storage/database. No sessions, messages,
materials or citations are created or changed. LLM requests use normal billing.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
import uuid
from pathlib import Path

from sqlalchemy import text

from api.services.guguta.chat import ChatService
from api.services.guguta.chat_agent import NotebookChatAgent
from api.services.guguta.pdf_evidence import PdfPageEvidence
from api.services.guguta.search import SearchService
from open_notebook.ai.guguta.chat import get_chat_provider
from open_notebook.ai.guguta.local_retrieval import LocalReranker
from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.database.guguta.engine import (
    actor_connection,
    create_engine_for_role,
)
from open_notebook.jobs.guguta.embeddings import get_provider
from open_notebook.storage.guguta.filesystem import FilesystemStorage


async def main(args):
    config = GugutaConfig(chat_agent_enabled=True)
    engine = create_engine_for_role(config, "api")
    actor, notebook, session = map(uuid.UUID, (args.actor, args.notebook, args.session))
    try:
        provider = get_chat_provider(config.chat_provider, config)
        embeddings = get_provider(
            config.embedding_provider, config.embedding_dimension, config
        )
        search = SearchService(
            engine,
            embeddings,
            reranker=LocalReranker(config)
            if config.rerank_provider == "local"
            else None,
        )
        pdf = PdfPageEvidence(engine, FilesystemStorage(config.storage_root))
        agent = NotebookChatAgent(
            search,
            pdf,
            max_rounds=config.chat_agent_max_rounds,
            max_calls=config.chat_agent_max_tool_calls,
        )
        service = ChatService(engine, search, provider)
        async with actor_connection(engine, actor) as conn:
            revision = (
                await conn.execute(
                    text(
                        "SELECT dn.context_revision FROM chat_sessions s JOIN digital_notebooks dn ON dn.id=s.notebook_id WHERE s.id=:session AND dn.id=:notebook"
                    ),
                    {"session": session, "notebook": notebook},
                )
            ).scalar_one()
            history = await service._history(conn, session, revision)
        if args.fresh:
            history = []
        if args.history_file:
            history = json.loads(Path(args.history_file).read_text())
            if not isinstance(history, list) or any(
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] not in ("user", "assistant")
                or not isinstance(message["content"], str)
                for message in history
            ):
                raise ValueError("History must contain user/assistant text messages.")
        start = time.monotonic()
        async with asyncio.timeout(config.chat_total_timeout_seconds):
            initial = []
            if args.exact:
                initial = await service._retrieve(
                    actor, notebook, args.question, history
                )
                initial = await pdf.enrich(actor, notebook, initial)
            acquired = await agent.retrieve(
                actor, notebook, provider, args.question, history, initial
            )
            answer = await provider.generate(args.question, acquired.chunks, history)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "question": args.question,
            "answer": answer.content,
            "model": answer.model,
            "latency_seconds": round(time.monotonic() - start, 2),
            "agent_tools": acquired.trace,
            "agent_usage": acquired.usage,
            "answer_usage": [
                answer.prompt_tokens,
                answer.completion_tokens,
                answer.estimated_cost,
            ],
            "citations": [
                {
                    "source": acquired.chunks[i].local_name,
                    "locator": acquired.chunks[i].locator,
                }
                for i in answer.cited
            ],
        }
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        for index, chunk in enumerate(acquired.chunks):
            if chunk.image_url:
                output.with_name(output.stem + f"-F{index + 1}.png").write_bytes(
                    base64.b64decode(chunk.image_url.split(",", 1)[1])
                )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("actor", "notebook", "session", "question", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Seed evidence with explicit-page retrieval.",
    )
    history_options = parser.add_mutually_exclusive_group()
    history_options.add_argument(
        "--fresh",
        action="store_true",
        help="Evaluate discovery without prior conversation hints.",
    )
    history_options.add_argument(
        "--history-file",
        help="Use a synthetic conversation JSON for read-only tutoring evaluation.",
    )
    asyncio.run(main(parser.parse_args()))
