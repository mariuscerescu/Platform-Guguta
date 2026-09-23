"""Provider-neutral entry point for the atomic Guguță embedding reindex."""

from __future__ import annotations

import argparse
import asyncio
import sys

from open_notebook.database.guguta.config import GugutaConfig
from scripts.guguta_reindex_openrouter import reindex

__all__ = ["reindex"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--maintenance",
        action="store_true",
        required=True,
        help="Confirms API and worker are stopped on the target database",
    )
    parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    config = GugutaConfig(_env_file=(".env.guguta", ".env.guguta.local"))
    print("Chunks reindexed:", asyncio.run(reindex(config)))


if __name__ == "__main__":
    main()
