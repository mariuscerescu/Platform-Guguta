"""Guguță smoke test (R103-style): synthetic two-account flow against the
containerized API. Uses only synthetic data and cleans nothing outside its
own fixtures.

Usage: uv run python scripts/smoke.py [--base-url http://127.0.0.1:5056]
"""

from __future__ import annotations

import argparse
import uuid

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5056")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    stamp = uuid.uuid4().hex[:8]

    client = httpx.Client(base_url=base, timeout=30)

    # 1. liveness + version
    r = client.get("/healthz")
    assert r.status_code == 200, r.text
    r = client.get("/versionz")
    assert r.status_code == 200, r.text
    print(f"1. healthz OK; commit: {r.json()['commit']}")

    # 2. two synthetic accounts
    def login(name: str) -> httpx.Client:
        r = client.post(
            "/api/v1/auth/dev-login",
            json={"display_name": name},
            headers={"Origin": "http://localhost:3000"},
        )
        assert r.status_code == 200, r.text
        csrf = r.headers["X-Guguta-CSRF"]
        cookie = r.cookies["guguta_session"]
        s = httpx.Client(
            base_url=base, timeout=30,
            cookies={"guguta_session": cookie},
            headers={"X-Guguta-CSRF": csrf,
                     "Origin": "http://localhost:3000"},
        )
        return s

    a = login(f"Smoke A {stamp}")
    b = login(f"Smoke B {stamp}")
    print("2. logins OK")

    # 3. A creates a notebook with a text source
    r = a.post("/api/v1/notebooks", json={"title": f"Smoke carnet {stamp}"})
    assert r.status_code == 201, r.text
    nb_id = r.json()["id"]
    r = a.post(
        f"/api/v1/notebooks/{nb_id}/sources/text",
        json={"title": "sursa",
              "text": "Text smoke: Chisinau este capitala Republicii Moldova."},
    )
    assert r.status_code == 201, r.text
    print("3. notebook + source OK (worker will process it)")

    # 4. isolation: B gets 404 on A's notebook
    r = b.get(f"/api/v1/notebooks/{nb_id}")
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"
    print("4. isolation OK (B -> 404)")

    print()
    print("SMOKE PASS (API) - 4/4 checks. Async processing is verified by the worker:")
    print("docker logs guguta-worker-1")


if __name__ == "__main__":
    main()
