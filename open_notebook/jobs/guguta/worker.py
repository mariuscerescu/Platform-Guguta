"""Guguță worker process (ADR-0002, GHID §6.3).

Run: python -m open_notebook.jobs.guguta.worker
(one process; concurrency kept conservative by default). The worker never
runs migrations and never holds a DB transaction across AI calls.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.database.guguta.engine import create_engine_for_role
from open_notebook.jobs.guguta.audio_overviews import process_audio_overview
from open_notebook.jobs.guguta.embeddings import get_provider
from open_notebook.jobs.guguta.flashcards import process_flashcard_deck
from open_notebook.jobs.guguta.handlers import process_material_version
from open_notebook.jobs.guguta.queue import claim
from open_notebook.jobs.guguta.quizzes import process_quiz
from open_notebook.storage.guguta.filesystem import FilesystemStorage

logger = logging.getLogger("guguta.worker")


class Worker:
    def __init__(self, config: GugutaConfig) -> None:
        self._config = config
        self._engine = create_engine_for_role(config, "worker")
        self._storage = FilesystemStorage(config.storage_root)
        self._provider = get_provider(config.embedding_provider, config.embedding_dimension, config)
        self._stopping = asyncio.Event()

    async def process_one(self) -> bool:
        """Claim and process exactly one job, with a heartbeat loop running
        for the duration (F11). Returns True if a job ran."""
        job = await claim(
            self._engine,
            lease_seconds=self._config.job_lease_seconds,
            worker_name=self._config.job_worker_name,
        )
        if job is None:
            return False
        logger.info("job revendicat: %s (%s)", job.id, job.job_type)

        from open_notebook.jobs.guguta.queue import heartbeat

        async def _heartbeat_loop() -> None:
            interval = max(5, self._config.job_lease_seconds // 4)
            while True:
                await asyncio.sleep(interval)
                try:
                    await heartbeat(self._engine, job.id, job.lease_token,
                                    extend_seconds=self._config.job_lease_seconds)
                except Exception:
                    logger.warning("heartbeat eșuat pentru job %s", job.id)

        hb_task = asyncio.create_task(_heartbeat_loop())
        try:
            if job.job_type == "process_material_version":
                await process_material_version(
                    self._engine,
                    self._storage,
                    self._provider,
                    job,
                    chunk_size_chars=self._config.chunk_size_chars,
                    overlap_chars=self._config.chunk_overlap_chars,
                )
            elif job.job_type == "generate_audio_overview":
                await process_audio_overview(
                    self._engine,
                    self._storage,
                    self._config,
                    job,
                )
            elif job.job_type == "generate_flashcards":
                await process_flashcard_deck(self._engine, self._config, job)
            elif job.job_type == "generate_quiz":
                await process_quiz(self._engine, self._config, job)
            else:
                logger.error("tip de job necunoscut: %s", job.job_type)
                from open_notebook.jobs.guguta.queue import fail

                await fail(
                    self._engine, job.id, job.lease_token,
                    f"tip necunoscut: {job.job_type}",
                    target_revision=job.target_revision, permanent=True,
                )
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
        return True

    async def run(self) -> None:
        logger.info("worker pornit (lease=%ss, poll=%ss)",
                    self._config.job_lease_seconds, self._config.job_poll_seconds)
        while not self._stopping.is_set():
            try:
                ran = await self.process_one()
            except Exception:
                logger.exception("eroare în bucla workerului")
                ran = False
            if not ran:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._config.job_poll_seconds
                    )
                except asyncio.TimeoutError:
                    pass

    def request_stop(self) -> None:
        self._stopping.set()

    async def aclose(self) -> None:
        await self._engine.dispose()


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = GugutaConfig()
    if config.environment not in ("development", "ci") and config.auth_mode == "test":
        raise RuntimeError("worker: test auth refused outside development/ci")
    worker = Worker(config)
    loop = asyncio.get_running_loop()
    stop = lambda: worker.request_stop()  # noqa: E731
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:  # pragma: no cover (Windows)
            signal.signal(sig, lambda *_: worker.request_stop())
    try:
        await worker.run()
    finally:
        await worker.aclose()


if __name__ == "__main__":
    asyncio.run(_main())
