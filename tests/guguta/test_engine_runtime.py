"""Runtime SQL tuning keeps caller options and transaction-local RLS intact."""
import uuid

import pytest
from sqlalchemy import make_url, text

from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.database.guguta.engine import (
    actor_connection,
    create_engine_for_role,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["api", "worker"])
async def test_runtime_connections_disable_jit_without_losing_options_or_actor_isolation(guguta_db, role):
    url = make_url(guguta_db[role + "_dsn"]).update_query_dict({"options": "-c statement_timeout=10000"})
    dsn = url.render_as_string(hide_password=False)
    config = GugutaConfig(_env_file=None, database_url_api=dsn if role == "api" else "",
                          database_url_worker=dsn if role == "worker" else "")
    engine = create_engine_for_role(config, role)
    actor = uuid.uuid4()
    try:
        async with actor_connection(engine, actor) as conn:
            row = (await conn.execute(text(
                "SELECT current_setting('jit'), current_setting('statement_timeout'), current_setting('app.actor_id')"
            ))).one()
            assert row == ("off", "10s", str(actor))
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT current_setting('app.actor_id', true)"))).scalar_one() in (None, "")
            assert (await conn.execute(text("SELECT count(*) FROM digital_notebooks"))).scalar_one() == 0
    finally:
        await engine.dispose()
