# Raport de livrare L7 — snapshot, import, revocare, GC

Data: 6 septembrie 2026 · Ramură: `guguta/foundation`

## 1. Elemente acoperite

- L7: toate elementele bifate cu dovezi; poarta G5 trecută.
- Criterii testate: **A07** (allowlist, zero activitate personală), **A08**
  (link și cod → același pachet), **A09/A21** (versiunile fixate; schimbările
  autorului nu ating copiile), **A10** (revocare → importuri noi refuzate,
  copiile rămân), **A15** (idempotency), **A16** (tranzacție atomică — fără
  succes fals), **A19** (re-verificare finală cu revocarea), **A20** (lock
  utilizator + cotă), **A28** (ștergerea carnetului autorului → revocare,
  copiile rămân).

## 2. Fișiere create/modificate

- `api/services/guguta/sharing.py`: creare snapshot (allowlist explicit pe
  surse „ready"), credențiale link+cod (hash-only), preview (metadate
  minime), import tranzacțional (lock destinatar → cotă → copie →
  ShareImport → idempotency → re-verificare finală), revocare (link+cod
  împreună + audit), `revoke_all_for_author` (A28), `_resolve_snapshot`
  tolerant pentru replay după revocare (R36).
- `alembic/versions/0006_share_lookup.py`: `guguta_share_lookup` SECURITY
  DEFINER (recipienții nu pot citi snapshoturile altora; funcția întoarce
  minimul necesar; tolerant la revocare pentru R36).
- `alembic/versions/0007_share_snapshot_notebook_nullable.py`:
  `share_snapshots.notebook_id` nullable + ON DELETE SET NULL — snapshotul
  supraviețuiește ștergerii carnetului ca record istoric.
- `api/services/guguta/notebooks.py`: delete → revocă pachetele active
  (cu audit) înaintea ștergerii.
- `open_notebook/jobs/guguta/gc.py`: GC în două faze (marcare după retenție +
  reverificare referințe la ștergere; rollback-safe, retry-safe).
- `api/services/guguta/catalog.py`: aceeași corecție de ordine
  (asocieri înainte de verificarea artefactelor) în instanțiere.

## 3. Comenzi executate și rezultate

| Comandă | Rezultat |
| --- | --- |
| `uv run pytest tests/guguta -q` | **51 passed** (45 + 6 L7) |
| `uv run ruff check <scopuri guguta>` | All checks passed |
| `uv run mypy <module guguta + tests>` | Success: 40 fișiere |
| `docker compose … run --rm migrator` | 0005 → 0006 → 0007 aplicate secvențial |

## 4. Probleme rezolvate

1. **Coliziune poziții materiale** (bug L3 prins de testele L7): poziția era
   `count(*)` — după ștergere+reîncărcare se colida cu poziția existentă;
   fix `MAX(position)+1`.
2. **`processing` vs `ready` la import**: verificarea artefactului înaintea
   creării asocierii era blocată de RLS (traseul de vizibilitate nu exista
   încă) — asocierile se creează primele, apoi statusul „ready" se aplică
   prin UPDATE cu EXISTS; joburile se envoiează doar pentru lipsă.
3. Replay după revocare: lookup-ul tolerant + ordinea replay→status check.
4. `FOR UPDATE` prin RLS pe rânduri străine — evitat și aici; re-verificare
   finală în tranzacție.

## 5. Teste neexecutate / limite

- Concurrency real (două tranzacții simultane import/revocare) — mecanismul
  de ordonare (re-verificare finală + lock pe rândul destinatarului) este
  testat funcțional; testul de concurență cu barieră rămâne la L9.
- Expirarea pachetelor — decizie explicită „fără expirare implicită"
  (documentată); se poate adăuga fără efect retroactiv.
- Ștergerea contului (A28 complet, cu ștergerea utilizatorului) — fluxul de
  cont vine cu L9; mecanismul de revocare există și e testat la nivel de
  serviciu.

## 6. Următoarea acțiune concretă

**L8 — Eliminare legacy:** audit importuri SurrealDB/surreal-commands în
runtime-ul țintă, dezactivarea rămășițelor, imagine proprie din commit
(API+worker+frontend), SBOM/licențe, cutover documentat — apoi L9
(verificări finale, restaurare, evaluare pedagogică).
