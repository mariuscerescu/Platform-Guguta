# Audit backend Guguță — 6 septembrie 2026

**Verdict: backendul funcționează pe fluxurile uzuale verificate, dar nu este pregătit pentru lansare cu elevi reali.** Există defecte reproduse de autorizare la nivelul rolurilor DB, validare OIDC, integritate tranzacțională, concurență și stări ale procesării. Acest raport evaluează codul de după remedierile workerului, nu presupune că auditul anterior descrie încă integral situația curentă.

## 1. Versiune, domeniu și metodă

- Repository local: `D:\Disk D 13-09-25\CS\AI Guguta\Platforma Guguta\open-notebook`.
- Branch: `guguta/foundation`; commit: `af1e5d66b20a153424a100d0548cdd22dd68aba1`.
- Contract verificat: documentele canonice din `docs/guguta/`, în special specificațiile, ghidul de implementare, ADR-urile și checklistul de deployment.
- Domeniu: aplicația `api.guguta_app`, rutele Guguță, servicii, autentificare/sesiuni, PostgreSQL/RLS/migrații, fișiere, parsare, worker/coadă, căutare/chat, catalog/import, infrastructura backend și testele existente.
- Nu s-a auditat vizual frontendul și nu s-a utilizat Computer Use. Nu s-a modificat codul aplicației, nu s-a făcut commit/push/deployment și nu s-au folosit documente ale elevilor.
- Verificări dinamice pe PostgreSQL/pgvector real, cu rolurile reale API și worker. Date sintetice, server Docker separat pe `127.0.0.1:55434`; API de audit pe `127.0.0.1:55435`.
- Injecțiile de erori și barierele de concurență sunt exclusiv în procesul testelor. Ele reproduc condiții specifice; nu reprezintă măsurători de frecvență în producție.

P1 = remediere înainte de pilot cu date reale; P2 = remediere înainte de acceptanța backendului sau de scenariul afectat. Nu a fost demonstrat un atac neautentificat care să ofere direct acces de administrator prin HTTP. O suită trecută nu poate demonstra absența tuturor defectelor.

## 2. Rezultate efective

| Verificare | Rezultat | Interpretare |
|---|---|---|
| Suita existentă `tests/guguta`, fără testul restore legat de containerul aplicației | **74 passed, 1 failed**, 34,23 s | Eșecul este fixture-ul OIDC cu DSN fix, explicat mai jos |
| Probe independente de acceptanță backend | **18 failed, 5 passed**, 13,13 s | 23 de cazuri; aserțiunile cer comportamentul corect, deci eșecurile expun defecte |
| Backup DB + fișiere, restaurare și autorizare după restore | **PASS** | Bază și director restaurate separat, descărcare verificată prin SHA-256 |
| Upgrade `0008 → 0009` cu date existente | **PASS** | Datele sintetice păstrate; schema și funcția introdusă prezente |
| Migrare de la zero până la `0009` | **PASS** | Executată pe DB de audit, inclusiv la inițializarea testelor |
| Build imagine Guguță din commitul auditat | **PASS** | Build cu dependențe din cache; nu demonstrează reproducibilitatea viitoare |
| `pip check` în imaginea Guguță | **PASS** | Niciun conflict declarat de dependențe în runtime-ul țintă |
| API + worker în containere/procese separate, HTTP real | **PASS** | PDF → ready → chat mock → copie fără chat → revocare → copia rămâne |
| Ruff pe backendul Guguță, migrații și testele existente | **PASS** | Fără modificări automate |
| Mypy pe backendul Guguță și testele existente | **PASS**, 46 fișiere | Nu acoperă erorile SQL și concurența descoperite |
| `pip check` în `.venv` comun upstream/development | **FAIL** | MoviePy 2.2.1 cere Pillow <12, instalat 12.3.0; nu este conflict al imaginii Guguță |

Suita existentă a produs 503 warnings, iar probele independente 92; numerele sunt păstrate pentru transparență, fără a echivala warnings cu vulnerabilități.

Testul existent `test_oidc_http_f01.py` reconstruiește un DSN pe portul 5433, ignorând serverul de test selectat. A eșuat la conectare, nu la o aserțiune a fluxului OIDC. Același flux HTTP, cu DSN corect către serverul izolat, **a trecut** în `test_oidc_real_routes_with_isolated_dsn`. Testul existent `test_a22_restore.py`, legat de `guguta-db-1`, nu a fost executat împotriva serviciilor utilizatorului; a fost înlocuit în audit cu restaurarea izolată descrisă mai sus.

### Dovezi păstrate

- [Probe independente](backend-audit-2026-09-06/test_backend_audit.py) și [rezultate JUnit](backend-audit-2026-09-06/results.xml).
- [Probe backup/upgrade](backend-audit-2026-09-06/test_backup_upgrade.py) și [rezultate JUnit](backend-audit-2026-09-06/restore-upgrade-results.xml): 2 passed.
- [Smoke HTTP între containere](backend-audit-2026-09-06/runtime_smoke.py) și [rezultat JSON](backend-audit-2026-09-06/runtime-results.json).
- Imagine construită: `guguta-backend-audit:af1e5d6`, image/config SHA-256 `bcf5b89858db1fd3f4d8792ce2a8a52705eb123aa9ff64ae27653764cc43fef4`.
- Smoke: `/healthz=ok`, `/readyz=ok/schema 0009`, `/versionz=af1e5d6`.
- Procesul API din container a rulat cu UID `10001`, verificat prin `id -u`.
- După probe au fost eliminate containerele, volumul, rețeaua și tagul imaginii create exclusiv pentru audit; dovezile de mai sus rămân în repository.

## 3. Defecte confirmate prin teste

### B01 — P1 — Timestampurile implicite sunt fixate la momentul migrării

**Cod:** `alembic/versions/0008_sync_column_defaults.py:27`, inclusiv liniile 45–47, 64–65 și 76. Instrucțiunile folosesc `SET DEFAULT 'now()'`, cu ghilimele. PostgreSQL stochează momentul interpretării literalului, nu o funcție de evaluat la fiecare inserare.

**Probă:** `test_timestamps_advance_between_inserts`: două carnete create în tranzacții distincte, la momente diferite, au același `created_at`. Defaultul citit din DB este concret `'2026-09-06 18:47:58.950578+00'::timestamp with time zone`.

**Impact:** ordonarea cronologică, vârsta mesajelor/joburilor, retenția și orice regulă care folosește aceste valori devin incorecte. Trigger-ele sau update-urile care setează explicit `now()` nu repară toate inserările afectate.

**Remediere:** migrare nouă, înainte, cu `SET DEFAULT now()` fără ghilimele, pentru toate coloanele afectate. Nu modifica doar modelul Python și nu rescrie arbitrar istoricul existent. Inventariază rândurile afectate și stabilește ce date pot fi recuperate din alte dovezi. Testează inserări înainte/după migrare și după restart. [PostgreSQL: valorile speciale de timp](https://www.postgresql.org/docs/17/datatype-datetime.html).

### B02 — P1 — Rolul worker poate crea o sesiune HTTP de administrator

**Cod:** `alembic/versions/0002_identity_provisioning.py:68`, funcția `guguta_create_session`; revizuiește și funcțiile `SECURITY DEFINER` din `0005_admin_credentials.py`.

**Probă:** `test_worker_cannot_mint_admin_http_session`: folosind exclusiv conexiunea DB a workerului, testul creează o sesiune pentru UUID-ul unui administrator sintetic. `/api/v1/auth/me` acceptă tokenul rezultat cu HTTP 200.

**Condiție:** acces SQL cu credentialele rolului worker și identificatorul contului țintă. Testul nu demonstrează obținerea acestor credentiale prin API de către un elev. Totuși, compromiterea unui proces destinat parsării poate traversa limita de privilegii către sesiuni administrative.

**Cauză:** acordarea accesului către un rol nu elimină accesul implicit `PUBLIC` la funcții. **Remediere:** revocă explicit `EXECUTE` de la `PUBLIC`, acordă fiecărei funcții doar rolurile necesare și verifică proprietarul, `search_path`, rolurile și toate funcțiile privilegiate. Operațiile care primesc `p_actor` trebuie analizate și pentru relația dintre identitatea afirmată și identitatea autorizată a apelantului. Adaugă matrice de teste API/worker/rol fără privilegii. [PostgreSQL: securitatea funcțiilor](https://www.postgresql.org/docs/17/sql-createfunction.html).

### B03 — P1 — Validatorul OIDC acceptă ID token fără `exp` sau `aud`

**Cod:** `open_notebook/auth/guguta/oidc.py:174`, în special `claims_options` la 192.

**Probe:** `test_oidc_required_claim_is_mandatory[exp]` și `[aud]` eșuează: tokenuri semnate cu cheia de test a emitentului sunt acceptate fără aceste claim-uri. Varianta fără `iss` este respinsă și testul trece.

**Impact/limită:** verificarea semnăturii rămâne activă; nu este o demonstrație de falsificare a semnăturii. Contractul de validare a expirării și a destinatarului este însă incomplet.

**Remediere:** declară explicit claim-urile obligatorii, validează tipurile și valorile, timpul, emitentul, audiența, subiectul și nonce; tratează corect audiențele multiple/`azp`. Normalizează excepțiile de validare. Extinde testele cu token expirat, claim absent, claim de tip greșit și audiență incompatibilă.

### B04 — P1 — Publicarea rezultatului workerului nu este atomică cu finalizarea jobului

**Cod:** `open_notebook/jobs/guguta/handlers.py:157` și `:177`; aceeași structură apare pe calea de eroare la 249/262.

**Probă:** `test_worker_publication_atomic_if_outer_transaction_fails` injectează o eroare la ieșirea tranzacției exterioare. Rezultatul observat este **job queued, 1 artefact publicat**.

**Cauză:** `system_connection` și `actor_connection` deschid conexiuni/tranzacții distincte. Comentariul „SAME transaction” nu corespunde implementării. Lockul jobului protejează o parte a ferestrei, dar commitul interior poate supraviețui rollbackului exterior.

**Remediere:** aceeași conexiune și tranzacție pentru verificarea lease-ului, contextul RLS, artefacte/chunks/embeddings, starea sursei și finalizarea jobului. Testează rollback la fiecare frontieră, lease expirat/pierdut și republicare idempotentă. Nu considera corecția completă doar pentru că un token deja înlocuit este respins.

### B05 — P1 — Limita de joburi per utilizator este ocolită pentru joburile queued

**Cod:** `open_notebook/jobs/guguta/queue.py:115`, expresia `A OR B AND cap`.

**Probă:** `test_queue_respects_per_user_cap`: sunt revendicate trei joburi ale aceluiași utilizator, deși limita transmisă este 2.

**Remediere:** grupează `(queued_eligibil OR lease_expirat_eligibil) AND cap`. Asigură limita și pentru revendicări simultane printr-un mecanism atomic per actor, nu numai printr-o numărare fără serializare. Propagă configurația din `Worker.process_one`, care în prezent nu transmite limita către `claim`.

### B06 — P1 — Un alt claim poate invalida ultima încercare încă activă

**Cod:** `open_notebook/jobs/guguta/queue.py:99`, sweep cu `attempts >= max_attempts` inclusiv pentru `running`.

**Probă:** `test_claim_does_not_fail_active_last_attempt`: la `max_attempts=1`, după primul claim și înainte de expirarea lease-ului, un nou claim mută jobul activ în `failed`.

**Remediere:** epuizarea bugetului trebuie aplicată când încercarea s-a încheiat sau lease-ul a expirat, nu la pornirea ultimei încercări permise. Separă deadline-ul absolut de bugetul de retry; testează doi workeri și succesul ultimei încercări.

### B07 — P1 — Un răspuns anulat este păstrat și expus în istoricul chatului

**Cod:** `api/services/guguta/chat.py:136` și faza de finalizare de la 361.

**Probă:** `test_cancelled_generation_not_exposed_as_answer`: contextul carnetului se schimbă în timpul generării; rezultatul este marcat `cancelled`, dar textul complet al răspunsului este returnat ulterior de endpointul de mesaje.

**Remediere:** la schimbarea reviziei, păstrează doar un eveniment de anulare fără textul rezultatului invalid sau definește explicit o reprezentare neexpusă drept răspuns. Nu permite salvarea lui ca notiță. Revalidarea reviziei și publicarea trebuie serializate și față de mutațiile surselor, nu doar față de alte mesaje ale sesiunii.

### B08 — P1 — PATCH sursă/notiță ignoră carnetul din URL

**Cod:** `api/services/guguta/sources.py:325`; `api/services/guguta/notes.py:145`.

**Probe:** `test_source_patch_enforces_parent_notebook`, `test_note_patch_enforces_parent_notebook`: sursa/notița din carnetul A poate fi modificată prin ruta carnetului B, HTTP 200 în loc de 404, pentru același proprietar.

**Impact:** nu s-a reprodus acces între proprietari; RLS respinge cazurile cross-user testate. Pentru surse, efectul este mai grav decât nepotrivirea URL-ului: se modifică sursa A, dar se incrementează revizia carnetului B, lăsând neinvalidat contextul lui A.

**Remediere:** `WHERE id=:id AND notebook_id=:n`, verificarea rezultatului și incrementarea reviziei părintelui verificat în aceeași tranzacție. Adaugă teste pentru surse, notițe și fiecare endpoint copil.

### B09 — P1 — Sursa poate deveni ready fără embeddings sau chunks

**Cod:** `open_notebook/jobs/guguta/handlers.py:190`, `zip(chunks, vectors)`.

**Probă:** `test_truncated_embeddings_cannot_publish_ready`: furnizorul de test returnează lista goală; workerul publică artefact complet și sursă `ready`, fără fragmente/vectori.

**Remediere:** înainte de publicare, validează numărul exact de vectori, dimensiunea fiecăruia și valori numerice finite. O eroare parțială a furnizorului trebuie să producă retry/eroare explicită, niciodată ready. Adaugă test și pentru un lot trunchiat nevid.

### B10 — P1 — Eșecul definitiv al jobului lasă sursa processing

**Cod:** `open_notebook/jobs/guguta/handlers.py:143`, `_fail_quietly`, plus sweep-ul din `queue.py`.

**Probă:** `test_final_provider_failure_marks_source_error`: furnizorul eșuează la ultima încercare; jobul devine `failed`, sursa rămâne `processing`.

**Impact:** utilizatorul așteaptă o procesare care nu mai rulează, iar retry-ul sursei cere starea `error`. **Remediere:** tranziție terminală coerentă job/sursă, atomică și protejată de lease, inclusiv la deadline și epuizarea încercărilor. Testează recuperarea prin retry și după restart.

### B11 — P2 — Două importuri simultane cu aceeași cheie produc HTTP 500

**Cod:** `api/services/guguta/sharing.py:328`, lookup-ul idempotent și tranzacția de import; verifică separat aceeași structură din `catalog.py:367`.

**Probă:** `test_import_same_key_concurrent_replays` sincronizează două cereri după lookup: rezultate **500 și 201**. Constrângerea unică împiedică duplicarea, dar endpointul nu livrează replay-ul promis.

**Remediere:** serializare pe actor/operație/cheie și relookup în secțiunea protejată sau rezervare atomică cu tratarea conflictului. Lockul snapshotului pentru import/revoke nu este suficient dacă rezultatul idempotent nu este recitit după obținerea lui. Ambele cereri trebuie să returneze aceeași copie; cheie reutilizată cu payload diferit trebuie să aibă conflict controlat.

### B12 — P2 — Chatul solicită o a doua conexiune în timp ce o reține pe prima

**Cod:** `api/services/guguta/chat.py:232` și `:254`; `api/services/guguta/search.py:89`.

**Probă:** `test_chat_works_with_one_connection_pool`, pool=1, overflow=0: cerere validă de chat produce HTTP 500 după timeoutul de checkout.

**Impact/limită:** reproducerea folosește un pool mic configurat explicit. Același model creează risc de epuizare sub concurență cu poolul implicit, dar pragul real nu a fost măsurat prin load test.

**Remediere:** transmite conexiunea existentă către retrieval sau rearanjează fazele pentru a nu reține o conexiune în timp ce aștepți alta. Nu rezolva exclusiv prin mărirea poolului; verifică concurența și timpul de așteptare al conexiunilor.

### B13 — P2 — Identități OIDC distincte cu același email provoacă UniqueViolation

**Cod:** `alembic/versions/0002_identity_provisioning.py`, `guguta_provision_user`; unicitatea emailului în modelul `users`.

**Probă:** `test_same_email_distinct_oidc_subjects_can_provision`, apeluri reale de provisioning cu identități distincte: al doilea produce `UniqueViolation`.

**Remediere:** definește explicit comportamentul pentru schimbarea subiectului/emitentului și coliziunea emailului. Identitatea externă se bazează pe issuer+subject. Nu lega automat conturi doar pe un email, mai ales neverificat. Fie permite modelul cerut, fie întoarce un conflict controlat cu flux sigur de rezolvare. Testul actual cere creare independentă și trebuie adaptat dacă produsul alege explicit un conflict controlat; excepția DB brută rămâne defect.

### B14 — P2 — Payloaduri invalide trec de DTO și ajung la HTTP 500

**Cod:** `api/routers/guguta_v1.py`, `VersionCreate.items`; `api/services/guguta/catalog.py:187`; `sources.py:123`.

**Probe:** `test_malformed_template_item_returns_validation_error`: `display_name=123` într-un element de versiune; `test_upload_rejects_nul_as_client_error`: text cu U+0000. Ambele întorc 500 în loc de eroare de validare.

**Remediere:** modele tipizate pentru elementele nested, lungimi și cardinalități explicite, validarea textelor incompatibile cu PostgreSQL înainte de persistență. Teste negative pentru UUID-uri, duplicate, tipuri greșite și limite. Nu trata toate excepțiile DB ca erori de client: păstrează distincția de integritate/infrastructură.

### B15 — P2 — Endpointul de configurare auth poate contrazice aplicația

**Cod:** `api/routers/guguta_v1.py:163`, apel nou `GugutaConfig()`; configurație reconstruită similar în `catalog.py:459` pentru cotă.

**Probă:** `test_auth_mode_uses_actual_app_config`: aplicație creată cu `auth_mode=oidc`, endpointul raportează `test`, preluat din mediu.

**Limită:** când configurația aplicației este identică mediului, simptomul poate lipsi. **Remediere:** o singură instanță validată de configurație, injectată în servicii și citită din starea aplicației. Testează și cotele injectate în operația de creare din șablon.

## 4. Probleme structurale și limite de producție

Aceste puncte sunt rezultate ale inspecției codului/configurației; nu sunt incluse artificial în numărul celor 18 cazuri eșuate.

### B16 — P1 — Furnizorii AI reali lipsesc încă

`open_notebook/ai/guguta/chat.py:81` acceptă numai `mock`; `open_notebook/jobs/guguta/embeddings.py` acceptă numai `hash`. Configurația refuză aceste valori în staging/production. Acest refuz este corect, dar înseamnă că nu există încă o configurație AI reală funcțională pentru lansare. Chatul verificat este determinist/simulat, iar vectorii hash nu sunt embeddings semantice.

**De realizat:** adaptor real, timeouturi și anulare, retry controlat, contabilizare reală de tokenuri/costuri, cote, selecție de model și evaluare RAG pe materiale românești. Închiderea deciziei de furnizor și evaluarea calității răspunsurilor sunt condiții separate de trecerea testelor software. Costul `0.0` și `guguta-mock-1` din chat nu sunt metrice de producție.

### B17 — P1 — Heartbeatul nu poate avansa în timpul operațiilor sincrone lungi

`worker.py:46` creează o sarcină async, dar `handlers.py:126–134` execută sincron extracția, segmentarea și `provider.embed` pe același event loop. Un apel lung poate bloca heartbeatul. Nu s-a provocat un consum masiv de resurse pentru a măsura durata până la pierderea lease-ului.

**De realizat:** separă I/O/procesarea blocantă de event loop; pentru parsere neîncredere folosește procese cu limite și anulare reală. Thread offload singur nu oferă terminarea unui parser blocat. Testează un furnizor lent, reînnoirea lease-ului observată din altă conexiune și preluarea sigură după moartea workerului.

### B18 — P1 — Limita fișierului comprimat nu limitează costul parsării

`sources.py:112–168` și `jobs/guguta/parsing.py`: încărcarea este citită înaintea verificărilor ulterioare, iar ZIP/XML/PDF pot expanda mult în memorie/timp. Limita în MiB nu înlocuiește limite pentru corp HTTP, volum decomprimat, număr de intrări, pagini, text extras, CPU și memorie. Nu s-a executat un atac de epuizare a resurselor.

**De realizat:** autorizare timpurie, limită de request la proxy/ASGI, lectură limitată, limite de decomprimare și proces izolat pentru parsare. Erorile trebuie să fie controlate și să nu lase fișiere/joburi orfane. Verifică și ordinea reală a slide-urilor PPTX, nu doar numele fișierelor XML, pentru citări corecte.

### B19 — P2 — Garbage collection nu acoperă întregul ciclu de viață

`open_notebook/jobs/guguta/gc.py:29`: un asset devine candidat doar dacă nu există niciun `material_version`. Nu există aici eliminarea versiunilor rămase fără carnete/șabloane/share-uri/joburi. La ștergere, rândul DB este eliminat înaintea fișierului; dacă storage-ul eșuează, următoarea rulare nu mai are rândul pentru retry.

**De realizat:** retenție pe graful complet de referințe, eliminare sigură a versiunilor neutilizate și tombstone/outbox pentru ștergerea bytes cu retry. Testează păstrarea copiei importate după ștergerea originalului, referințe concurente și eșecul storage-ului. Un restore reușit nu validează GC-ul.

### B20 — P2 — Procedura de deployment nu este încă executabilă fără presupuneri

`docs/guguta/RUNBOOK_CUTOVER.md`, secțiunea 2, invocă `docker compose` fără fișierul `docker-compose.guguta.yml`. La rădăcina forkului există și configurația upstream. Precizează peste tot fișierul, proiectul, mediul și digesturile țintă; verifică scripts menționate și serviciile reale.

`docker/guguta/api.Dockerfile` folosește tagul mutabil `python:3.12-slim` și intervale de versiuni pip. Buildul curent a trecut, dar același commit poate produce dependențe diferite ulterior. Introdu lock/hashes, SBOM și scanare de vulnerabilități a imaginii reale în CI. Auditul de față nu a făcut o certificare CVE/licențe pentru toate dependențele și nu declară imaginea lipsită de vulnerabilități.

### B21 — P2 — Suita de acceptanță are lacune de mediu și scenariu

Elimină DSN-ul fix din testul OIDC și numele fix al containerului aplicației din restore. Fixture-ul comun recreează `guguta_test` și schimbă parolele rolurilor: rulează-l numai pe infrastructură disposable, niciodată pe serverul unei aplicații reale. În CI, absența DB pentru jobul de integrare trebuie să fie eșec vizibil, nu o suită aparent verde fără probe DB.

Adoptă probele de concurență și rollback din acest audit ca teste permanente. Păstrează auditul istoric cu rezultatele inițiale; nu rescrie XML-ul vechi pentru a ascunde defectele după remediere. Înregistrează rezultate noi pe noul commit.

### B22 — P2 — Retenția conturilor, observabilitatea și operarea cer acceptanță separată

Nu există în rutele auditate un flux complet de ștergere a contului cu tratarea sesiunilor, fișierelor și copiilor importate. Helperul de revocare a share-urilor nu este echivalent. Politica trebuie să păstreze explicit copiile legitime deja importate și să definească retenția datelor private.

Verifică în staging alertele reale, joburile terminale blocate, spațiul storage, backupurile și un restore periodic. Redactează erorile interne/provider înainte de expunere: workerul poate persista textul excepțiilor în `last_error`. Nu s-a demonstrat o scurgere de chei reale în acest audit, dar textul brut al excepției nu trebuie să fie contractul public al endpointului de joburi.

## 5. Ce funcționează și ce nu trebuie eliminat

- Separarea runtime-ului Guguță de stiva SurrealDB upstream este prezentă în Dockerfile; imaginea țintă a fost construită și rulată.
- Fluxul OIDC prin rutele reale trece cu emitent simulat și DSN izolat. Aceasta nu închide B03 și B13.
- Protecția cross-user pentru descărcare și modificarea notițelor a trecut cu HTTP 404. B02 este o altă limită de securitate: rolul DB al workerului.
- Numele de fișier românesc poate fi descărcat cu `filename*=UTF-8''`, iar bytes PDF au fost păstrați identic.
- În aceeași sesiune de chat, după eliminarea sursei și schimbarea contextului, markerul din răspunsul vechi nu este retransmis furnizorului: `test_history_exclusion_same_session_after_source_change` a trecut. B07 privește expunerea răspunsului anulat, nu negarea acestei corecții.
- Importul uzual copiază materialele fără sesiuni de chat. Revocarea oprește importurile viitoare și lasă copia existentă accesibilă. Acest comportament a fost verificat și după restore.
- Upgrade-ul și backup/restore-ul de date și fișiere au trecut. Nu validează automat runbookul pentru infrastructura viitoare sau rollbackul oricărei migrări.

Prin urmare, recomand continuarea pe implementarea actuală cu remedieri țintite. Rezultatele nu justifică rescrierea de la zero, dar nici declararea backendului „complet funcțional”.

## 6. Ordinea recomandată a remedierilor

1. **DB și autentificare:** B01, B02, B03; migrare nouă pentru defaults și privilegii. Reexecută toate testele de RLS/sesiuni și upgrade pe DB populată.
2. **Worker și integritate:** B04, B05, B06, B09, B10, B17. O singură tranzacție de publicare, stări terminale coerente și teste cu doi workeri/lease/rollback.
3. **Contextul carnetului și chat:** B08, B07, B12. Părinte verificat, revizie corectă, răspunsuri anulate neexpuse și fără checkout DB imbricat.
4. **Contracte API:** B11, B13, B14, B15. Idempotency concurent, coliziuni de identitate controlate, DTO-uri stricte și configurație unică.
5. **Pregătirea pentru operare:** B16, B18–B22. AI real, limite de parsare, retenție/GC, CI și proceduri executate în staging.

### Checklist de închidere a auditului

- [ ] Fiecare constatare are remediere, commit și test de regresie sau decizie explicită de produs pentru contractul relevant.
- [ ] Toate cele 23 de cazuri ale probei independente trec; orice schimbare a așteptării este justificată, nu simpla adaptare la defect.
- [ ] Suita originală trece complet pe DSN/container izolat, inclusiv OIDC și restore fără valori hardcodate.
- [ ] Rolul worker nu poate crea sesiuni sau administra credentiale; privilegii verificate după migrare de la zero și upgrade.
- [ ] Jobul și rezultatul publicat au aceeași soartă la rollback/crash; ultima încercare activă nu este invalidată de alt worker.
- [ ] Eșecurile finale apar coerent în UI/API ca surse recuperabile prin retry.
- [ ] Modificarea surselor invalidează exact carnetul corect; răspunsurile anulate nu sunt expuse/salvate drept răspunsuri valide.
- [ ] Import simultan/replay/revocare/retragere șablon testate determinist, cu numărul și identitatea copiilor verificate.
- [ ] Provider AI real și embeddings reale validate pe corpus ro-MD, inclusiv citări, întrebări fără răspuns și prompt injection în materiale.
- [ ] Timeouturi, rate limits/cote, anulare, costuri și alertare demonstrate, nu doar câmpuri de configurație.
- [ ] Parsare izolată cu limite, retenție/GC și ștergerea contului testate conform politicii produsului.
- [ ] Imagine fixată și scanată, migrare staging, backup DB+storage, restore și rollback repetate pe release candidate.
- [ ] Raport nou de acceptanță indică exact commitul, imaginea, datele și verificările rămase neexecutate.

## 7. Reproducerea probelor

**Numai pe server de audit disposable la `127.0.0.1:55434`.** Fixture-ul upstream distruge/recreează `guguta_test` și resetează parolele rolurilor de pe serverul selectat. Proba independentă refuză colectarea pe alt host/port; această verificare nu dovedește singură că serverul este disposable.

Din rădăcina repository-ului, după crearea serverului izolat PG17+pgvector și a mediului Python:

```powershell
$env:GUGUTA_TEST_DATABASE_URL='postgresql+psycopg://guguta_migrator:guguta_audit_local@127.0.0.1:55434/guguta'
.venv\Scripts\python.exe -m pytest docs/guguta/backend-audit-2026-09-06/test_backend_audit.py -q --basetemp=.backend-audit-rerun -p no:cacheprovider --disable-warnings --tb=short
```

Testul de restore necesită în plus Docker CLI, containerul izolat `guguta-backend-audit-20260906` și permisiunea de creare/ștergere doar a bazelor sintetice. Smoke-ul HTTP cere API și worker separate, conectate la baza `guguta` de pe acel server și la același volum privat de audit. OIDC și AI folosesc implementări de test; nu sunt necesare chei reale.

Infrastructura disposable este o dependență a reproducerii, nu un deployment oferit prin aceste scripturi. Serviciile aplicației utilizatorului nu trebuie înlocuite cu cele de audit.
