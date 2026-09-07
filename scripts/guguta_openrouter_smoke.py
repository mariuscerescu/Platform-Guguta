"""Synthetic HTTP smoke for the isolated API on port 55435; no keys printed."""
import json
import time
import uuid
from pathlib import Path

import httpx


def main():
    with httpx.Client(base_url="http://127.0.0.1:55435", timeout=125) as client:
        ready = client.get("/readyz")
        assert ready.status_code == 200
        login = client.post("/api/v1/auth/dev-login", json={"display_name": "Synthetic OR " + uuid.uuid4().hex})
        assert login.status_code == 200
        headers = {"Origin": "http://localhost:3001", "X-Guguta-CSRF": login.headers["X-Guguta-CSRF"]}
        response = client.post("/api/v1/notebooks", headers=headers, json={"title": "OpenRouter smoke sintetic"})
        assert response.status_code == 201
        nb = response.json()["id"]
        response = client.post(f"/api/v1/notebooks/{nb}/sources/text", headers=headers, json={
            "title": "Biologie sintetică", "text": "Fotosinteza folosește energia luminii pentru a transforma apa și dioxidul de carbon în substanțe organice. În proces se eliberează oxigen."})
        assert response.status_code == 201
        sid = response.json()["source"]["id"]
        deadline = time.monotonic() + 70
        while True:
            status = client.get(f"/api/v1/notebooks/{nb}/sources/{sid}").json()["status"]
            if status == "ready":
                break
            assert status != "error" and time.monotonic() < deadline, status
            time.sleep(0.25)
        session = client.post(f"/api/v1/notebooks/{nb}/sessions", headers=headers, json={}).json()["id"]
        response = client.post(f"/api/v1/notebooks/{nb}/sessions/{session}/messages", headers=headers, json={
            "content": "De ce au plantele nevoie de lumină?", "idempotency_key": uuid.uuid4().hex})
        assert response.status_code == 200, response.text
        messages = client.get(f"/api/v1/notebooks/{nb}/sessions/{session}/messages").json()
        answer = messages[-1]
        citations = client.get(f"/api/v1/notebooks/{nb}/sessions/{session}/messages/{answer['id']}/citations").json()
        assert answer["status"] == "complete" and citations
        result = {"date": "2026-09-07", "ready": ready.json(), "separate_api_worker": True,
                  "real_openrouter": True, "answer": answer["content"], "citations": len(citations)}
        Path("docs/guguta/openrouter-docker-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
