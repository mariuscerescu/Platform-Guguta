# Raport de livrare L6 — catalog și șabloane

Data: 6 septembrie 2026 · Ramură: `guguta/foundation`

## 1. Elemente acoperite

- L6: toate elementele bifate cu dovezi; poarta G4 trecută (două copii se
  modifică independent, proveniența păstrată).
- Criterii testate: **A02** (copii independente, aceeași versiune fixată),
  **A03** (eliminare material din copie — șablonul, alte copii și căutarea
  rămân valide), **A05** („Începe din nou" din ediția publicată curentă),
  **A14** (ediții noi nu actualizează copiile; retragerea nu le afectează),
  **A15** (idempotency: aceeași cheie → aceeași copie; cheie nouă → copie
  nouă), **A18** (ștergerea unui carnet nu ruinează materialele partajate),
  **A06** (copie cu zero activitate personală).

## 2. Fișiere create/modificate

- `api/services/guguta/catalog.py`: ciclu de viață draft→publicare→retragere,
  verificarea extracției complete la publicare, instanțiere tranzacțională
  (versiune fixată + carnet + NotebookSource-uri noi + idempotency), manifest
  imuabil (trigger L1), re-verificare finală a ediției în tranzacție.
- `api/routers/guguta_v1.py`: `/api/v1/admin/catalog/templates…` (editor/admin)
  + `/api/v1/catalog/templates…` (public/instanțiere).
- `api/guguta_app.py`: wiring + handler-e (404/409/422).
- `tests/guguta/test_catalog_l6.py`: 5 teste (publicare/vizibilitate,
  instanțiere A02/A03/A18, idempotency A15, ediții A05/A14, retragere).

## 3. Comenzi executate și rezultate

| Comandă | Rezultat |
| --- | --- |
| `uv run pytest tests/guguta -q` | **45 passed** (40 + 5 L6) |
| `uv run ruff check <scopuri guguta>` | All checks passed |
| `uv run mypy <module guguta + tests>` | Success: 37 fișiere |

## 4. Probleme rezolvate

1. **RLS + `FOR UPDATE`**: studentul nu poate încuia rândul șablonului
   altuia (SELECT FOR UPDATE cere trecerea și prin politica UPDATE) —
   înlocuit cu re-verificarea ediției la finalul tranzacției, care serializează
   corect cu retragerea (stil A19).
2. Ordinea inserărilor în `create_version` — `template_materials` înaintea
   rândului `template_versions` viola WITH CHECK; versiunea draft se creează
   acum prima, manifestul se finalizează după materiale.
3. `r2.status_code == 200` pentru replay — ruta declară 201; test ajustat la
   contract (`replayed: true` + același notebook).

## 5. Teste neexecutate / limite

- Retragerea ediției vechi când există DOUĂ ediții publicate („current" =
  cea cu număr maxim) — acoperit parțial; cazul explicit de „recreare ediție
  veche" rămâne ulterior (specificații §4.2).
- GC-ul fizic (două faze) este L7 — testul A18 verifică doar disponibilitatea
  materialului după ștergerea unui carnet, nu ștergerea fizică a octeților.
- Interfața publică a catalogului (frontend) rămâne din L5.

## 6. Următoarea acțiune concretă

**L7 — Snapshot, import și revocare:** ShareSnapshot/ShareMaterial
(allowlist explicit), token/cod pentru același pachet, preview + import
tranzacțional cu cote, idempotency pe destinatar, serializare
import↔revocare (A19), GC în două faze, ștergerea carnetului/contului autor
cu revocarea pachetelor active — teste A07–A10/A15/A16/A19–A21/A28.
