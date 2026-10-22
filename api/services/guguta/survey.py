"""Anonymous school feedback: fixed questionnaire, public aggregates and comments."""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.exceptions import InvalidInputError

SURVEY_VERSION = "guguta-schools-2026-v1"
PUBLIC_SURVEY_PATHS = frozenset({
    "/api/v1/survey", "/api/v1/survey/session", "/api/v1/survey/responses",
    "/api/v1/survey/results", "/api/v1/survey/comments", "/api/v1/survey/export.csv",
})
TEXT_IDS = ("q19", "q20")


def _options(labels: list[str], codes: list[str] | None = None) -> list[dict[str, str]]:
    return [{"value": (codes[i] if codes else str(i + 1)), "label": label} for i, label in enumerate(labels)]


def _choice(number: int, title: str, labels: list[str], *, section: str,
            kind: str = "single", codes: list[str] | None = None,
            exclusive: list[str] | None = None) -> dict[str, Any]:
    return {"id": f"q{number:02d}", "number": number, "title": title, "section": section,
            "type": kind, "required": True, "options": _options(labels, codes),
            "max_choices": 3 if kind == "multiple" else 1, "exclusive": exclusive or []}


def _rating(number: int, title: str, labels: list[str], section: str = "Experiența ta") -> dict[str, Any]:
    question = _choice(number, title, labels, section=section, kind="rating")
    question["options"].append({"value": "na", "label": "Nu am folosit / Nu pot aprecia"})
    return question


EXTENT = ["Deloc", "În mică măsură", "Într-o oarecare măsură", "În mare măsură", "În foarte mare măsură"]
INTENTION = ["Cu siguranță nu", "Probabil nu", "Nu sunt sigur(ă)", "Probabil da", "Cu siguranță da"]
QUESTIONS: list[dict[str, Any]] = [
    _choice(1, "În ce clasă studiezi?", [*[f"Clasa {c}" for c in ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]], "Prefer să nu spun"],
            section="Despre experiența ta", codes=[*[str(i) for i in range(1, 13)], "skip"]),
    _choice(2, "Cât de des folosești aplicații digitale pentru a învăța?",
            ["Niciodată", "Rareori", "Uneori", "Des", "Foarte des"], section="Despre experiența ta"),
    _choice(3, "Cum ai explorat Guguță până acum?",
            ["Am folosit platforma singur(ă)", "Am folosit platforma cu ajutorul cuiva", "Am urmărit doar prezentarea", "Încă nu am explorat platforma"], section="Despre experiența ta"),
    _rating(4, "Ce impresie generală ți-a lăsat platforma Guguță?",
            ["Foarte slabă", "Slabă", "Nici slabă, nici bună", "Bună", "Foarte bună"]),
    _rating(5, "Cât de utilă crezi că ți-ar fi Guguță pentru învățare?",
            ["Deloc utilă", "Puțin utilă", "Moderat de utilă", "Utilă", "Foarte utilă"]),
    _rating(6, "Cât de clare ți s-au părut explicațiile lui Guguță?",
            ["Deloc clare", "Puțin clare", "Moderat de clare", "Clare", "Foarte clare"]),
    _rating(7, "Ai primit suficiente informații pentru a înțelege răspunsurile lui Guguță?", EXTENT),
    _rating(8, "În ce măsură te-a ajutat Guguță să înțelegi mai bine lecția?", EXTENT),
    _rating(9, "Cât de bine s-au potrivit răspunsurile lui Guguță cu întrebările tale?",
            ["Deloc", "Puțin", "Moderat", "Bine", "Foarte bine"]),
    _rating(10, "Cât de ușor ți-a fost să găsești și să deschizi materialele din carnet?",
            ["Foarte greu", "Greu", "Nici greu, nici ușor", "Ușor", "Foarte ușor"], "Folosirea platformei"),
    _rating(11, "Cât de ușor ai înțeles vocea lui Guguță?",
            ["Foarte greu", "Greu", "Nici greu, nici ușor", "Ușor", "Foarte ușor"], "Folosirea platformei"),
    _rating(12, "Cât de interesantă ți s-a părut învățarea cu Guguță?",
            ["Deloc interesantă", "Puțin interesantă", "Moderat de interesantă", "Interesantă", "Foarte interesantă"]),
    _rating(13, "Cât de plăcut ți s-a părut personajul Guguță?",
            ["Deloc plăcut", "Puțin plăcut", "Moderat de plăcut", "Plăcut", "Foarte plăcut"]),
    _rating(14, "Ai dori să mai folosești Guguță la școală sau acasă?", INTENTION, "Pe viitor"),
    _rating(15, "Ai recomanda Guguță unui coleg?", INTENTION, "Pe viitor"),
    _choice(16, "Ce funcții ți s-au părut cele mai utile?",
            ["Materialele și carnetele digitale", "Chatul cu Guguță", "Conversația vocală", "Quizurile și testele", "Cardurile de învățare", "Rezumatele audio", "Niciuna, deocamdată", "Nu am încercat încă funcțiile"],
            section="Preferințe și dificultăți", kind="multiple", codes=["materials", "chat", "voice", "quiz", "flashcards", "audio", "none", "na"], exclusive=["none", "na"]),
    _choice(17, "Cum ai prefera să înveți cu ajutorul lui Guguță?",
            ["Să citesc explicații și exemple", "Să ascult explicații", "Să văd imagini și scheme", "Să rezolv quizuri și exerciții", "Să discut și să pun întrebări", "Să încerc activități practice", "Nu am o preferință"],
            section="Preferințe și dificultăți", kind="multiple", codes=["read", "listen", "images", "practice", "discuss", "activities", "none"], exclusive=["none"]),
    _choice(18, "Ce dificultăți ai întâmpinat?",
            ["Autentificarea sau înregistrarea", "Găsirea materialelor", "Înțelegerea explicațiilor", "Vocea sau microfonul", "Încărcarea lentă ori erorile", "Folosirea pe telefon", "Nu am întâmpinat dificultăți", "Nu am folosit încă platforma"],
            section="Preferințe și dificultăți", kind="multiple", codes=["login", "materials", "explanations", "voice", "speed", "phone", "none", "na"], exclusive=["none", "na"]),
    {"id": "q19", "number": 19, "title": "Ce ți-a plăcut cel mai mult la Guguță?", "type": "text", "section": "Cu propriile cuvinte", "required": False, "max_length": 1000, "options": []},
    {"id": "q20", "number": 20, "title": "Ce ai schimba sau îmbunătăți la Guguță?", "type": "text", "section": "Cu propriile cuvinte", "required": False, "max_length": 1000, "options": []},
]


def questionnaire() -> dict[str, Any]:
    return {"version": SURVEY_VERSION, "title": "Părerea ta despre Guguță", "questions": QUESTIONS}


def validate_answers(answers: dict[str, Any]) -> dict[str, Any]:
    if set(answers) != {q["id"] for q in QUESTIONS}:
        raise InvalidInputError("Chestionarul trebuie să conțină toate cele 20 de întrebări.")
    clean: dict[str, Any] = {}
    for question in QUESTIONS:
        value = answers[question["id"]]
        error = f"Verifică răspunsul la întrebarea {question['number']}."
        if question["type"] == "text":
            if not isinstance(value, str) or len(value) > 1000 or "\x00" in value:
                raise InvalidInputError(error)
            value = value.strip()
            # Public comments must not accidentally expose contact details.
            if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:\+?\d[\s().-]*){8,}", value):
                raise InvalidInputError(f"La întrebarea {question['number']}, elimină adresele de email sau numerele de telefon. Răspunsul va fi public.")
        else:
            allowed = {option["value"] for option in question["options"]}
            if question["type"] == "multiple":
                if (not isinstance(value, list) or not 1 <= len(value) <= question["max_choices"]
                        or any(not isinstance(item, str) or item not in allowed for item in value)
                        or len(set(value)) != len(value)
                        or (len(value) > 1 and set(value) & set(question["exclusive"]))):
                    raise InvalidInputError(error)
            elif not isinstance(value, str) or value not in allowed:
                raise InvalidInputError(error)
        clean[question["id"]] = value
    return clean


class SurveyService:
    def __init__(self, engine: AsyncEngine, server_secret: str) -> None:
        self.engine = engine
        self._key = hashlib.sha256((server_secret + ":anonymous-survey-v1").encode()).digest()

    def start(self) -> dict[str, str]:
        submission = str(uuid.uuid4())
        payload = f"{submission}:{int(time.time()) + 86400}:{secrets.token_hex(8)}"
        encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        signature = hmac.new(self._key, encoded.encode(), hashlib.sha256).hexdigest()
        return {"submission_id": submission, "token": encoded + "." + signature}

    def _verify(self, submission: uuid.UUID, token: str) -> None:
        try:
            encoded, signature = token.split(".")
            expected = hmac.new(self._key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            identifier, expiry, _ = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode().split(":")
            if identifier != str(submission) or int(expiry) < time.time():
                raise ValueError()
        except (ValueError, UnicodeError):
            raise InvalidInputError("Sesiunea sondajului a expirat. Reia trimiterea; răspunsurile tale rămân în formular.") from None

    async def submit(self, submission: uuid.UUID, token: str, version: str,
                     answers: dict[str, Any], acknowledged: bool) -> dict[str, bool]:
        self._verify(submission, token)
        if version != SURVEY_VERSION or acknowledged is not True:
            raise InvalidInputError("Confirmă că ai înțeles că răspunsurile sunt anonime și publice.")
        clean = validate_answers(answers)
        async with self.engine.begin() as conn:
            await conn.execute(text("SELECT guguta_survey_submit(:id, :version, CAST(:answers AS jsonb))"),
                               {"id": submission, "version": version, "answers": json.dumps(clean, ensure_ascii=False)})
        # Same response for an accepted submission and its harmless retry.
        return {"saved": True}

    async def results(self) -> dict[str, Any]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT * FROM guguta_survey_counts(:version)"),
                                       {"version": SURVEY_VERSION})).mappings().all()
        total = next((int(r["responses"]) for r in rows if r["question"] == "__total__"), 0)
        counts = {(r["question"], r["answer"]): int(r["responses"]) for r in rows}
        questions = []
        for question in QUESTIONS:
            options = [{**option, "count": counts.get((question["id"], option["value"]), 0)} for option in question["options"]]
            valid_count = sum(option["count"] for option in options if option["value"] in {"1", "2", "3", "4", "5"}) if question["type"] == "rating" else None
            mean = (round(sum(int(o["value"]) * o["count"] for o in options if o["value"] in {"1", "2", "3", "4", "5"}) / valid_count, 2)
                    if valid_count else None)
            questions.append({**question, "options": options, "rated_count": valid_count, "mean": mean,
                              "written_count": counts.get((question["id"], "__written__"), 0)})
        return {"version": SURVEY_VERSION, "total": total, "questions": questions}

    async def comments(self, question: str, offset: int = 0, limit: int = 20) -> list[str]:
        if question not in TEXT_IDS:
            raise InvalidInputError("Întrebare necunoscută.")
        async with self.engine.connect() as conn:
            rows = await conn.execute(text("SELECT answer FROM guguta_survey_comments(:version, :question, :offset, :limit)"),
                                      {"version": SURVEY_VERSION, "question": question, "offset": offset, "limit": limit})
            return list(rows.scalars().all())

    async def export(self) -> str:
        results = await self.results()
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Întrebare", "Variantă / răspuns scris", "Număr", "Total chestionare"])
        for question in results["questions"]:
            for option in question["options"]:
                writer.writerow([question["title"], option["label"], option["count"], results["total"]])
            if question["type"] == "text":
                offset = 0
                while comments := await self.comments(question["id"], offset, 50):
                    for comment in comments:
                        # Prevent spreadsheet formula execution in public exports.
                        safe = "'" + comment if comment.lstrip().startswith(("=", "+", "-", "@")) else comment
                        writer.writerow([question["title"], safe, 1, results["total"]])
                    offset += len(comments)
        # This export deliberately has no per-pupil rows or identifiers.
        return "\ufeff" + output.getvalue()
