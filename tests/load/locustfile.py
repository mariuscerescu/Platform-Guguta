"""Load testing for the Guguță API (GHID §12.4).

Usage:
    pip install locust
    locust -f tests/load/locustfile.py --host http://127.0.0.1:5056 \
        --users 20 --spawn-rate 2 --run-time 60s

Simulates realistic user flows: login, create notebook, upload text source,
search, chat, list notes. Uses synthetic data only.
"""

import uuid

from locust import HttpUser, between, task


class GugutaUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Login with a unique synthetic user."""
        self.name = f"Load {uuid.uuid4().hex[:8]}"
        resp = self.client.post(
            "/api/v1/auth/dev-login",
            json={"display_name": self.name},
            headers={"Origin": "http://localhost:3001"},
        )
        if resp.status_code != 200:
            self.environment.runner.quit()
            return
        self.csrf = resp.headers.get("X-Guguta-CSRF", "")
        self.cookie = resp.cookies.get("guguta_session", "")
        self.headers = {
            "X-Guguta-CSRF": self.csrf,
            "Origin": "http://localhost:3000",
            "Cookie": f"guguta_session={self.cookie}",
        }
        self.nb_id = self._create_notebook()

    def _create_notebook(self) -> str:
        resp = self.client.post(
            "/api/v1/notebooks",
            json={"title": f"Load carnet {uuid.uuid4().hex[:6]}"},
            headers=self.headers,
        )
        return resp.json()["id"]

    @task(4)
    def list_notebooks(self):
        self.client.get("/api/v1/notebooks", headers=self.headers)

    @task(3)
    def add_text_source(self):
        self.client.post(
            f"/api/v1/notebooks/{self.nb_id}/sources/text",
            json={"title": f"Load src {uuid.uuid4().hex[:4]}",
                  "text": f"Conținut de test pentru load testing {uuid.uuid4().hex[:8]}."},
            headers=self.headers,
        )

    @task(2)
    def search(self):
        self.client.post(
            f"/api/v1/notebooks/{self.nb_id}/search",
            json={"query": "conținut", "mode": "text"},
            headers=self.headers,
        )

    @task(1)
    def list_sources(self):
        self.client.get(
            f"/api/v1/notebooks/{self.nb_id}/sources", headers=self.headers
        )
