"""L5 tests: DOCX/PPTX extraction, notes, admin credentials, reports."""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.guguta.test_materials_worker import _config, _drain, _headers, _login

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def client(guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(_config(guguta_db["api_dsn"]))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3000"
    ) as c:
        yield c


@pytest_asyncio.fixture()
async def worker(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    from open_notebook.database.guguta.engine import create_engine_for_role
    from open_notebook.jobs.guguta.embeddings import HashEmbeddingProvider
    from open_notebook.jobs.guguta.worker import Worker
    from open_notebook.storage.guguta.filesystem import FilesystemStorage

    class TestWorker(Worker):
        def __init__(self) -> None:
            cfg = _config(guguta_db["worker_dsn"])
            self._config = cfg
            self._engine = create_engine_for_role(cfg, "worker")
            self._storage = FilesystemStorage("./.guguta-test-storage")
            self._provider = HashEmbeddingProvider(dimension=8)
            self._stopping = __import__("asyncio").Event()

    w = TestWorker()
    yield w
    await w.aclose()



def _cookies(auth: dict[str, str]) -> dict[str, str]:
    return {"guguta_session": auth["cookie"]}


def _make_docx(paragraphs: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        body = "".join(
            f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
            for p in paragraphs
        )
        zf.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>',
        )
    return buf.getvalue()


def _make_pptx(slides: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        for i, text in enumerate(slides, start=1):
            runs = "".join(
                f'<a:t>{part}</a:t>' for part in [text]
            )
            zf.writestr(
                f"ppt/slides/slide{i}.xml",
                f'<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>{runs}</p:spTree></p:cSld></p:sld>',
            )
    return buf.getvalue()


async def _setup_admin(client: AsyncClient, guguta_db: dict[str, Any]) -> dict[str, str]:
    """Create an admin user: provision as normal user, promote via migrator."""
    import sqlalchemy as sa

    auth = await _login(client, f"Admin {uuid.uuid4().hex[:6]}")
    me = (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()
    eng = sa.create_engine(guguta_db["migrator_dsn"])
    with eng.connect() as conn:
        conn.exec_driver_sql(
            f"UPDATE users SET roles = ARRAY['user','admin'] WHERE id = '{me['id']}'"
        )
        conn.commit()
    eng.dispose()
    return auth


async def _setup_notebook(client: AsyncClient, auth: dict[str, str]) -> str:
    nb = (
        await client.post(
            "/api/v1/notebooks", json={"title": "Carnet L5"},
            cookies=_cookies(auth), headers=_headers(auth),
        )
    ).json()
    return nb["id"]


# ---------------------------------------------------------------------------
# DOCX / PPTX extraction
# ---------------------------------------------------------------------------


async def test_docx_extraction_pipeline(
    client: AsyncClient, worker: Any
) -> None:
    auth = await _login(client, f"L5 docx {uuid.uuid4().hex[:6]}")
    nb_id = await _setup_notebook(client, auth)
    docx = _make_docx(
        ["Primul paragraf despre sistemul solar.",
         "Al doilea paragraf descrie planetele."]
    )
    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/sources/file",
        files={"file": ("document.docx", docx,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201, resp.text
    source_id = resp.json()["source"]["id"]
    await _drain(worker)
    detail = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sources/{source_id}", cookies=_cookies(auth)
    )).json()
    assert detail["status"] == "ready", detail.get("status_detail")

    results = (await client.post(
        f"/api/v1/notebooks/{nb_id}/search",
        json={"query": "planetele", "mode": "both"},
        cookies=_cookies(auth),
    )).json()
    assert len(results) >= 1
    assert "paragraph" in results[0]["locator"]


async def test_pptx_extraction_pipeline(client: AsyncClient, worker: Any) -> None:
    auth = await _login(client, f"L5 pptx {uuid.uuid4().hex[:6]}")
    nb_id = await _setup_notebook(client, auth)
    pptx = _make_pptx(["Slide cu introducere în geometrie.",
                       "Slide doi: triunghiuri dreptunghice."])
    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/sources/file",
        files={"file": ("prezentare.pptx", pptx,
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201, resp.text
    source_id = resp.json()["source"]["id"]
    pptx_job_id = resp.json()["job_id"]
    await _drain(worker)
    detail = (await client.get(
        f"/api/v1/notebooks/{nb_id}/sources/{source_id}", cookies=_cookies(auth)
    )).json()
    job = (await client.get(f"/api/v1/jobs/{pptx_job_id}", cookies=_cookies(auth))).json()
    assert detail["status"] == "ready", (
        f"{detail.get('status_detail')!r} job={job['status']} err={job['last_error']!r}"
    )
    results = (await client.post(
        f"/api/v1/notebooks/{nb_id}/search",
        json={"query": "triunghiuri", "mode": "both"},
        cookies=_cookies(auth),
    )).json()
    assert len(results) >= 1
    assert results[0]["locator"].get("slide") == 2


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


async def test_notes_crud_and_save_answer(
    client: AsyncClient, worker: Any, guguta_db: dict[str, Any]
) -> None:
    auth = await _login(client, f"L5 notes {uuid.uuid4().hex[:6]}")
    nb_id = await _setup_notebook(client, auth)

    # create
    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/notes",
        json={"title": "Rezumat", "content": "Ideile principale ale lecției."},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201, resp.text
    note = resp.json()
    assert note["source_message_id"] is None

    # update
    resp = await client.patch(
        f"/api/v1/notebooks/{nb_id}/notes/{note['id']}",
        json={"content": "Ideile principale, revizuite."},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 200
    assert resp.json()["content"].endswith("revizuite.")

    # save an assistant answer as a note
    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/sources/text",
        json={"text": "Textul sursă pentru chat.", "title": "sursă"},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    await _drain(worker)
    session = (await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions", json={},
        cookies=_cookies(auth), headers=_headers(auth),
    )).json()
    sent = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages",
        json={"content": "Textul sursă"},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert sent.status_code == 200
    assistant_id = sent.json()["assistant_message_id"]
    resp = await client.post(
        f"/api/v1/notebooks/{nb_id}/sessions/{session['id']}/messages/"
        f"{assistant_id}/save-as-note",
        json={"title": "Răspuns salvat"},
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["source_message_id"] == assistant_id

    # isolation: another user sees nothing
    other = await _login(client, f"L5 other {uuid.uuid4().hex[:6]}")
    resp = await client.get(
        f"/api/v1/notebooks/{nb_id}/notes", cookies=_cookies(other)
    )
    assert resp.status_code == 404

    # delete
    resp = await client.delete(
        f"/api/v1/notebooks/{nb_id}/notes/{note['id']}",
        cookies=_cookies(auth), headers=_headers(auth),
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Admin credentials + reports
# ---------------------------------------------------------------------------


async def test_admin_credentials_roles_and_rotation(
    client: AsyncClient, guguta_db: dict[str, Any]
) -> None:
    user = await _login(client, f"L5 user {uuid.uuid4().hex[:6]}")
    admin = await _setup_admin(client, guguta_db)

    # user is denied (A23)
    resp = await client.post(
        "/api/v1/admin/credentials",
        json={"provider": "chat", "name": "openai-main", "secret_value": "sk-test"},
        cookies=_cookies(user), headers=_headers(user),
    )
    assert resp.status_code == 403

    # admin sets; list shows metadata only
    resp = await client.post(
        "/api/v1/admin/credentials",
        json={"provider": "chat", "name": "openai-main", "secret_value": "sk-test-123"},
        cookies=_cookies(admin), headers=_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    cred = resp.json()
    assert cred["key_id"] == "k1"

    listing = (await client.get(
        "/api/v1/admin/credentials", cookies=_cookies(admin)
    )).json()
    assert len(listing) == 1
    assert "secret" not in str(listing).lower()
    assert "encrypted_payload" not in str(listing).lower()

    # rotation: same provider value under the primary key
    resp = await client.post(
        f"/api/v1/admin/credentials/{cred['id']}/rotate",
        json={},
        cookies=_cookies(admin), headers=_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["rotated"] is True

    # decryption works for the provider path and is audited
    from open_notebook.auth.guguta.actor import ActorContext
    from open_notebook.database.guguta.engine import create_engine_for_role

    app_state_engine = create_engine_for_role(
        _config(guguta_db["api_dsn"]), "api"
    )
    admin_actor = ActorContext(
        actor_id=uuid.UUID(
            (await client.get("/api/v1/auth/me", cookies=_cookies(admin))).json()["id"]
        ),
        display_name="admin",
        roles=frozenset({"user", "admin"}),
    )
    admin_svc = AdminServiceForTest(app_state_engine)
    secret = await admin_svc.decrypt_for_use(admin_actor, "chat", "openai-main")
    assert secret == "sk-test-123"
    await app_state_engine.dispose()

    # delete
    resp = await client.delete(
        f"/api/v1/admin/credentials/{cred['id']}",
        cookies=_cookies(admin), headers=_headers(admin),
    )
    assert resp.status_code == 200
    listing = (await client.get(
        "/api/v1/admin/credentials", cookies=_cookies(admin)
    )).json()
    assert listing == []


class AdminServiceForTest:
    def __init__(self, engine: Any) -> None:
        from api.services.guguta.admin import AdminService

        self._svc = AdminService(
            engine,
            _crypto_for_test(),
        )

    async def decrypt_for_use(self, actor: Any, provider: str, name: str) -> str:
        return await self._svc.decrypt_for_use(actor, provider, name)


def _crypto_for_test() -> Any:
    from open_notebook.auth.guguta.crypto import CredentialCrypto

    return CredentialCrypto(
        {"k1": "dev-only-insecure-key-change-me"}, "k1"
    )


async def test_content_reports_user_and_admin(
    client: AsyncClient, guguta_db: dict[str, Any]
) -> None:
    user = await _login(client, f"L5 rep {uuid.uuid4().hex[:6]}")
    admin = await _setup_admin(client, guguta_db)
    await _setup_notebook(client, user)

    resp = await client.post(
        "/api/v1/reports",
        json={"target_type": "message", "target_id": str(uuid.uuid4()),
              "reason": "Răspuns nepotrivit pentru clasă"},
        cookies=_cookies(user), headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text

    # admin sees the report
    reports = (await client.get(
        "/api/v1/admin/reports", cookies=_cookies(admin)
    )).json()
    assert len(reports) >= 1
    assert reports[0]["action"] == "content_report" or \
        "reason" in str(reports[0])

    # regular user cannot list reports
    resp = await client.get("/api/v1/admin/reports", cookies=_cookies(user))
    assert resp.status_code == 403
