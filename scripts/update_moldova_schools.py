"""Refresh registration suggestions from the public MEC SICE institution lists.

These lists cover SICE participants, not the entire national school network.
Only institution names/localities are retained; no pupil or staff data is used.
Run: python3 scripts/update_moldova_schools.py
"""

import json
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

SOURCES = [
    "https://mec.gov.md/ro/content/"
    "lista-institutiilor-de-invatamant-general-care-implementeaza-sistemul-informational-catalog",
    "https://mec.gov.md/ro/content/"
    "lista-institutiilor-de-invatamant-general-care-implementeaza-primul-sistemul-informational",
]
OUTPUT = Path(__file__).resolve().parents[1] / "frontend-guguta/public/schools-md.json"


def normalize(value: str) -> str:
    return " ".join(value.translate(str.maketrans("şţŞŢ", "șțȘȚ")).split())


def folded(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value.casefold())
        if not unicodedata.combining(char) and char.isalnum()
    )


class SchoolTables(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] = []
        self.cell: list[str] | None = None
        self.depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.depth += 1
        elif tag == "tr" and self.depth:
            self.row = []
        elif tag in ("td", "th") and self.depth:
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(normalize(" ".join(self.cell)))
            self.cell = None
        elif tag == "tr" and len(self.row) == 3:
            self.rows.append(self.row)
        elif tag == "table":
            self.depth -= 1


def main() -> None:
    schools: dict[str, dict[str, str]] = {}
    for url in SOURCES:
        request = Request(url, headers={"User-Agent": "Guguta-school-directory/1.0"})
        with urlopen(request, timeout=30) as response:
            parser = SchoolTables()
            parser.feed(response.read().decode("utf-8"))
        if len(parser.rows) < 100:
            raise RuntimeError(f"Unexpected MEC table structure: {url}")
        for district, locality, name in parser.rows:
            if not all((district, locality, name)) or folded(name).startswith("cticescoalavirtuala"):
                continue
            school = {"name": name, "locality": locality, "district": district}
            schools[folded(f"{name}|{locality}|{district}")] = school

    data = {
        "source": "Ministerul Educației și Cercetării al Republicii Moldova",
        "sources": SOURCES,
        "retrieved_on": datetime.now(timezone.utc).date().isoformat(),
        "coverage": "Instituții din listele publice SICE; nu este registrul național complet.",
        "schools": sorted(schools.values(), key=lambda school: folded(
            f"{school['district']} {school['locality']} {school['name']}"
        )),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(schools)} institutions to {OUTPUT}")


if __name__ == "__main__":
    main()
