# Raport de livrare L5 (backend) — formate MVP, notițe, administrare AI

Data: 6 septembrie 2026 · Ramură: `guguta/foundation`

## 1. Elemente acoperite

- L5 backend: DOCX/PPTX extracție, notițe private + salvarea răspunsurilor,
  configurare centrală AI cu criptarea cheilor și rotație, cote + măsurare
  costuri/încercări, dezactivare server-side funcții amânate, raportare
  conținut problematic — toate testate.
- **Frontend L5 deschis**: localizare ro-MD UI, design tokens, pagina
  principală, panouri desktop/mobile, verificări accesibilitate — rămân
  livrarea principală înainte de L6 (elemente marcate în checklist).

## 2. Fișiere create/modificate

- `open_notebook/jobs/guguta/parsing.py`: extracție DOCX (paragrafe) și PPTX
  (slide-uri) prin stdlib XML/zip — fără dependențe noi; locatori
  `paragraph`/`slide`; erori explicite pentru documente corupte/ fără text.
- `open_notebook/auth/guguta/crypto.py`: Fernet (SHA-256 din secret per
  key_id) + MultiFernet pentru rotație; config `credential_encryption_keys`
  (dict key_id→secret) + `credential_key_primary_id`.
- `alembic/versions/0005_admin_credentials.py`: tabel `admin_credentials`
  (RLS activ, fără politici runtime — acces doar prin funcții), funcții
  SECURITY DEFINER cu verificarea rolului admin ÎN DB:
  `guguta_admin_assert/set/list/get/delete` + `guguta_credential_decrypt`
  (audit automat la set/update/delete/decrypt).
- `api/services/guguta/admin.py`: set/list (metadata-only)/delete/rotate +
  decriptare pentru folosire; raportare conținut → `audit_events`.
- `api/services/guguta/notes.py` + rute `/notes` + `save-as-note`.
- `api/routers/guguta_v1.py`: rute admin/notes/reports; `api/guguta_app.py`:
  wiring + excepții.
- `api/services/guguta/chat.py`: tokeni/cost înregistrați pe mesaje
  (estimări pentru mock).

## 3. Comenzi executate și rezultate

| Comandă | Rezultat |
| --- | --- |
| `uv run pytest tests/guguta -q` | **40 passed** (+5 L5) |
| `uv run ruff check <scopuri guguta>` | All checks passed |
| `uv run mypy <module guguta + tests>` | Success: 35 fișiere |

## 4. Probleme rezolvate (inclusiv un bug real de integritate)

1. **Coruperea fișierelor binare pe Windows** (găsită de testele PPTX):
   `os.open` fără `O_BINARY` traducea LF→CRLF la scriere — PDF/DOCX/PPTX
   salvate corupte. Fix: `O_BINARY` în `FilesystemStorage.save_bytes`.
   `/!\ Notă de produs: aceeași categorie de bug poate exista în alte părți
   din upstream — de verificat la L8 cutover.`
2. `rotate_credential` citea rândul direct (RLS refuza) — citire prin funcție
   `guguta_admin_get_credential` (admin assert în DB).
3. Listarea rapoartelor nu includea coloana `action`.

## 5. Teste neexecutate / limite

- Interfața (frontend) — itemii deschiși din L5.
- Criptarea cheilor: rotația cu chei multiple (MultiFernet) este implementată,
  dar testul acoperă rotația sub aceeași cheie primară; test cu cheie secundă
  de rămasă la primul ciclu real de rotație.
- Costurile sunt estimări pe caractere pentru mock — numere reale cu D-02.

## 6. Următoarea acțiune concretă

**L6 — Catalog și șabloane:** Template/TemplateVersion/TemplateMaterial,
draft→verificare→publicare→retragere, manifest imuabil, instanțiere
tranzacțională cu ID-uri locale noi, „Începe din nou" pe ediția publicată
curentă, teste A02/A03/A05/A14/A18.

Alternativ (dacă se dorește UI înainte de catalog): construcția frontendului
Guguță (elementele deschise din L5).
