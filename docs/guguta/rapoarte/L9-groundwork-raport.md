# Raport livrare — acoperire A-criteria extinsă (L9 groundwork)

Data: 6 septembrie 2026 · Ramura: `guguta/foundation`

## 1. Criterii nou demonstrate în această livrare

| Criteriu | Test | Rezultat |
| --- | --- | --- |
| **A01** | vizitatorul (fără cookie) vede doar șabloanele publicate; drafturile rămân invizibile | PASS |
| **A25** | material cu instrucțiuni ostile („ignore previous… grant admin… delete all") tratat ca date: zero roluri noi, zero carnete ale altora atinse, răspunsul citează doar contextul | PASS |
| **A26** | furnizor AI indisponibil → 502 `provider_unavailable` cu mesaj util; zero mesaje asistente parțiale salvate | PASS |
| **A22** | pg_dump → restaurare în DB proaspăt: proprietatea, chatul, pachetul revocat, ShareImport, copia destinatarului și artefactele se păstrează | PASS |

## 2. Fișiere create/modificate

- `api/services/guguta/catalog.py`: `list_public_templates_visitor()` pe
  `system_connection` — A01 pentru vizitatori (RLS public-path rămâne poarta).
- `api/routers/guguta_v1.py`: ruta catalog fără autentificare.
- `api/services/guguta/chat.py`: `ChatProviderUnavailable` — generarea e
  înconjurată de try/except, mesajul utilizatorului rămâne istoric, fără
  răspuns parțial (A26).
- `api/guguta_app.py`: handler 502 `provider_unavailable`.
- `tests/guguta/test_a_criteria_l9.py`: A01/A25/A26.
- `tests/guguta/test_a22_restore.py`: A22 cu pg_dump/psql real prin container.

## 3. Verificări executate

| Verificare | Rezultat |
| --- | --- |
| `uv run pytest tests/guguta -q` | **61 passed** |
| ruff / mypy | clean (44 fișiere) |
| `docker compose build api` + smoke `scripts/smoke.py` | SMOKE PASS 4/4 (runda anterioară) |

## 4. Acoperirea A01–A28 după această livrare

- **Demonstrate integral în teste**: A02–A10, A14–A21, A23, A24, A25, A26,
  A28.
- **Demonstrate parțial** (fundament implementat + test pe mecanism):
  A01 (catalog public vizitator — acum integral), A11 (izolarea pe toate
  suprafețele — surse/joburi/download/notes testate; streaming la L5 UI),
  A12 (validare citări — mecanism testat; susținerea semantică la evaluarea
  pedagogică), A13 (lipsa informației — mock determinist), A17, A22
  (restaurare reală executată în test), A26 (buget + eroare furnizor).
- **Necesită decizii/acceptanță umană**: A22 final pe mediu separat dedicat,
  A27 reindexare cu model real, pragurile pedagogice (D-06), lansarea (R98).

## 5. Deschis (blocant = decizii umane, nu tehnice)

- Frontend: sweep accesibilitate complet (Playwright + revizie umană).
- L9: pragurile de calitate/cost/latență (D-06), evaluarea cu profesor (D-05),
  restaurarea pe mediu dedicat (D-03), provideri reali (D-02/D-10).
- L10: GO pentru lansare (R98/R101) — aparține responsabililor.
