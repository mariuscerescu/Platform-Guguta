"""HTTP smoke against the disposable audit API and separate worker only."""
import hashlib
import json
import time
import uuid
from pathlib import Path

import httpx
from tests.guguta.test_materials_worker import _make_pdf

results = {}
with httpx.Client(base_url="http://127.0.0.1:55435", timeout=15) as client:
    def call(method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, (path, response.status_code, response.text[:300])
        return response

    for endpoint in ("healthz", "readyz", "versionz"):
        results[endpoint] = call("GET", "/" + endpoint).json()

    def login():
        client.cookies.clear()
        response = call("POST", "/api/v1/auth/dev-login", json={"display_name": "Runtime audit " + uuid.uuid4().hex})
        return {"Cookie": "guguta_session=" + response.cookies["guguta_session"],
                "X-Guguta-CSRF": response.headers["X-Guguta-CSRF"], "Origin": "http://localhost:3000"}

    author = login()
    nb = call("POST", "/api/v1/notebooks", 201, headers=author, json={"title": "Runtime audit"}).json()["id"]
    payload = _make_pdf(["Fotosinteza transforma energia luminii. Plantele produc oxigen."])
    sid = call("POST", f"/api/v1/notebooks/{nb}/sources/file", 201, headers=author,
               files={"file": ("manual.pdf", payload, "application/pdf")}).json()["source"]["id"]
    deadline = time.monotonic() + 20
    while True:
        status = call("GET", f"/api/v1/notebooks/{nb}/sources/{sid}", headers=author).json()["status"]
        if status == "ready":
            break
        assert status != "error" and time.monotonic() < deadline, status
        time.sleep(0.2)
    results["separate_worker_pdf"] = "PASS"
    session = call("POST", f"/api/v1/notebooks/{nb}/sessions", 201, headers=author, json={}).json()["id"]
    answer = call("POST", f"/api/v1/notebooks/{nb}/sessions/{session}/messages", headers=author,
                  json={"content": "Fotosinteza"}).json()
    results["mock_chat"] = "PASS"
    share = call("POST", f"/api/v1/notebooks/{nb}/shares", 201, headers=author, json={"source_ids": [sid]}).json()
    recipient = login()
    copied = call("POST", "/api/v1/imports", 201, headers=recipient,
                  json={"token": share["token"], "idempotency_key": uuid.uuid4().hex}).json()["notebook_id"]
    sources = call("GET", f"/api/v1/notebooks/{copied}/sources", headers=recipient).json()
    data = call("GET", f"/api/v1/notebooks/{copied}/sources/{sources[0]['id']}/download", headers=recipient).content
    assert hashlib.sha256(data).digest() == hashlib.sha256(payload).digest()
    call("GET", f"/api/v1/notebooks/{nb}", 404, headers=recipient)
    assert call("GET", f"/api/v1/notebooks/{copied}/sessions", headers=recipient).json() == []
    call("POST", f"/api/v1/notebooks/{nb}/shares/{share['share_id']}/revoke", headers=author)
    call("POST", "/api/v1/imports", 409, headers=recipient,
         json={"token": share["token"], "idempotency_key": uuid.uuid4().hex})
    call("GET", f"/api/v1/notebooks/{copied}", headers=recipient)
    results["material_only_copy_revocation_isolation_download"] = "PASS"

Path(__file__).with_name("runtime-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))
