# Raport de livrare L2 — identitate și CRUD autorizat

Data: 6 septembrie 2026 · Ramură: `guguta/foundation`

## 1. Elemente acoperite

- L2: 11/12 elemente bifate cu dovezi; adaptorul OIDC este implementat, dar
  proba completă cu issuer fals rămâne deschisă (element notat „în curs”).
- Criterii: A04/A11 pentru CRUD (testate), A23 (fundament testat — suprafața
  Guguță nu expune rute admin/podcasturi/surse).

## 2. Fișiere create/modificate

- `open_notebook/auth/guguta/`: `actor.py` (ActorContext + ActorDenied→403),
  `sessions.py` (sesiuni opace, cookie, CSRF-HMAC, expirare absolută +
  inactivitate, revocare), `oidc.py` (Authorization Code + PKCE S256,
  state/nonce semnate HMAC, discovery, JWKS, validare ID token: issuer/aud/
  exp/nonce; asociere pe issuer+subject).
- `open_notebook/database/guguta/config.py`: câmpuri sesiune/OIDC/server
  secret/api_mode; validatorul de producție interzice și secretul default,
  wildcard CORS și OIDC incomplet.
- `alembic/versions/0002_identity_provisioning.py`: funcții SECURITY DEFINER
  `guguta_provision_user`, `guguta_create_session`, `guguta_resolve_session`,
  `guguta_revoke_session`, `guguta_revoke_all_for_user` + granturi EXECUTE
  pentru `guguta_api`. Motiv: login-ul are loc înainte de a exista un context
  de actor; RLS refuză corect INSERT-uri anonime — provisioningul trece printr-
  o interfață îngustă, auditată, deținută de rolul migrator.
- `api/services/guguta/notebooks.py`: CRUD cu ActorContext, paginare cu clamp,
  sortare allowlist, excepții tipizate (subclase `open_notebook.exceptions`).
- `api/routers/guguta_v1.py`: `/api/v1/auth/{dev-login,logout,me}`,
  `/api/v1/notebooks` CRUD; rute subțiri; origin ignorat din client.
- `api/guguta_app.py`: fabrica aplicației Guguță — doar /api/v1 + healthz/
  readyz (rutele upstream NU sunt montate: R26 la nivel de suprafață),
  middleware sesiune + CSRF/Origin, maparea excepțiilor la codurile
  contractului (401/403/404/422/500), readyz verifică schema cu rolul runtime.
- `tests/guguta/test_auth_notebooks_api.py`: 10 teste API end-to-end.
- CI + `scripts/check.ps1`: scoper extins pe modulele noi.

## 3. Comportament înainte/după

- **Înainte:** parolă comună de instanță; orice rută upstream accesibilă;
  fără utilizatori; CRUD fără proprietate.
- **După:** login sintetic izolat (dev/ci + auth_mode=test); sesiuni opace cu
  token hashuit în DB; CSRF obligatoriu la mutații (Origin verificat);
  CRUD carnet cu proprietate pe server — obiecte străine → 404 fără divulgare;
  suspendarea contului taie accesul imediat.

## 4. Comenzi executate și rezultate

| Comandă | Rezultat |
| --- | --- |
| `uv run pytest tests/guguta -q` | **24 passed** (14 L1 + 10 L2) |
| `uv run ruff check <scopuri guguta>` | All checks passed |
| `uv run mypy <module guguta + tests>` | Success: no issues (15 fișiere) |

Teste L2 notabile: login+me; 401 fără sesiune; mutație fără CSRF→403; Origin
străin→403; logout→revocare; CRUD izolat A/B (listă, ID direct, PATCH/DELETE
pe obiect străin→404, origin din server); paginare+clamp+sort allowlist
(`sort=1; DROP TABLE users`→422); rute admin/inportate→404/405; suspendare→401.

## 5. Probleme rezolvate

1. Provisioning/sesiuni înainte de actor: RLS refuza INSERT-urile anonime —
   rezolvat cu funcții SECURITY DEFINER înguste (migrația 0002).
2. Bug SQL de precedență în resolverul de sesiuni (OR ne-parantezat) — fixat.
3. `str(engine.url)` maschează parola (`***`) — a lovit a treia oară; teste
   folosesc DSN-urile pre-randate din fixtură.
4. DELETE pe obiect străin întorcea 200 cu `deleted:false` — acum 404 (fără
   divulgarea existenței).
5. Coloane NOT NULL fără server_default (`email_verified`, `result`) —
   auditate și completate (auditul rulează ca verificare locală).

## 6. Teste neexecutate

- Flux OIDC complet cu issuer fals (token exchange + JWKS + validare): adaptor
  implementat, proba rămâne în L2 — următoarea acțiune.
- Expirarea inactivității nu are test unitar dedicat (implementată în
  `guguta_resolve_session`; verificabilă prin manipularea last_seen_at).

## 7. Limite / riscuri

- Rate limiting nu este încă implementat (login/dev-login) — L5/lansare.
- `dev-login` folosește issuer-ul `test`; în producție rutele sunt dezactivate
  și startup-ul refuză configurația — de demonstrat în staging (R19).
- Frontend-ul Guguță nu consumă încă API-ul (L5); contractele există în cod.

## 8. Următoarea acțiune concretă

**L3 — Materiale și worker:** adaptor de stocare privată (chei generate de
server), upload PDF cu limite/MIME/pagini, MaterialVersion+NotebookSource în
tranzacție, ProcessingJob cu lease/heartbeat, worker PDF (extracție, locatori,
segmentare, embeddinguri în loturi), stări UI-ready la API.
