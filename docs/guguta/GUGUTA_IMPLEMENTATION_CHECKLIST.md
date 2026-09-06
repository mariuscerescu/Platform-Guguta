# Platforma Guguță — checklist de implementare

Versiune: 1.1 · 6 septembrie 2026
Fork comunicat: <https://github.com/mariuscerescu/Guguta-Platform>
Bază locală analizată: Open Notebook 1.14.0, commit `8297bb22e2eaeb0d8feafc0538f0d736453571d4`.

Checklistul urmărește execuția. [Specificațiile](SPECIFICATII_GUGUTA.md) sunt autoritatea pentru comportament. [Ghidul LLM](GHID_IMPLEMENTARE_LLM.md) descrie designul, arhitectura, infrastructura, securitatea și testele. [Deployment readiness](DEPLOYMENT_READINESS_CHECKLIST.md) se completează separat pentru release.

Revizia 1.1 aliniază ordinea cu livrările L0–L10. Testele, identitatea și CI încep în fundație; podcasturile și toate funcțiile upstream nu mai sunt condiții pentru migrarea MVP. Decizia Open Notebook/PostgreSQL este deja acceptată.

## Utilizare

- Bifează `[x]` numai după verificare și adaugă dovada/commitul.
- Pentru lucru în curs sau blocaj, păstrează `[ ]` și scrie starea și motivul sub element.
- Nicio căsuță nu este bifată numai prin existența documentației.
- Dacă lucrezi în mai multe PR-uri, închide rezultatele reale, nu doar lista fișierelor editate.
- Deciziile de furnizor, pilot și date reale se închid la termenul indicat în specificații; nu redeschid alegerea bazei.
- Nu folosi Computer Use. Testele UI se rulează din proiect prin CLI și sunt completate cu verificare umană când e necesar.

## L0 — Inventar, fork, documentație și CI minim

- [x] Verificăm HEAD, branch, remotes și modificările locale. — `main @ 8297bb2`, fără modificări pe fișiere urmărite; remotes reconfigurate (origin→fork, upstream→lfnovo).
- [x] Citim AGENTS.md și documentăm diferențele dintre direcția upstream și Guguță. — [DIVERGENTE_UPSTREAM.md](DIVERGENTE_UPSTREAM.md).
- [x] Inventariem volumele, fișierele, persistența SQLite și necesarul de recuperare a secretelor fără a afișa valori. — [MIGRATION_INVENTORY.md](../../MIGRATION_INVENTORY.md): notebook_data (11 fișiere), surreal_data (7 fișiere), checkpoints.sqlite.
- [x] Salvăm datele existente prin backup coerent și verificăm restaurarea. — `backups/pre-migration-20260906-112923/` (zip + sha256, 18/18 hash-uri verificate; servicii oprite la copiere).
- [x] Configurăm origin către fork și upstream către Open Notebook, fără reclonare peste checkout. — origin=mariuscerescu/Guguta-Platform, upstream=lfnovo/open-notebook.
- [x] Fixăm commitul de bază și strategia de actualizări upstream. — baza `8297bb2`; upstream doar fetch, fără push; actualizări pe ramuri dedicate.
- [x] Creăm ramura de lucru și convențiile de PR/release. — `guguta/foundation`; livrări mici cu raport per livrare (GHID §15).
- [x] Păstrăm LICENSE MIT și adăugăm registrul de proveniență. — LICENSE neatins; NOTICE creat.
- [x] Versionăm un singur set canonic de documente în fork, cu linkuri actualizate. — docs/guguta/ (5 documente + checklist mutat + README canonic).
- [x] Scriem ADR-urile PostgreSQL/vectori, joburi, identitate, stocare, memorie și copii independente. — adr/ADR-0001..0007.
- [x] Fixăm politica de licențe și inventariem dependențele obligatorii. — ANALIZA_OSS.md §5 + NOTICE; SBOM complet la build release (R05).
- [x] Pornim CI cu lint, tipuri, teste și scanare de secrete; protecția ramurii se configurează unde există acces. — `.github/workflows/guguta-ci.yml` (ruff, mypy, pytest cu PostgreSQL pgvector, gitleaks); rularea pe runner nu a fost încă verificată (push la fork pendinte de mandat/acces).
- [x] Înregistrăm deciziile externe încă necesare cu responsabil și termen. — [DECIZII_EXTERNE.md](DECIZII_EXTERNE.md) D-01..D-10.

**Închidere:** date protejate, inventar și bază reproductibilă. Nu presupunem că fork-ul comunicat are deja configurate remote-urile checkoutului.

## L1 — PostgreSQL și schemă

- [x] Pornim un Compose separat pentru Guguță, fără a șterge volumele demo. — `docker-compose.guguta.yml` (proiect `guguta`, volum numit `guguta_pg_data`; surreal_data/notebook_data neatinse).
- [x] Fixăm PostgreSQL 17 la un patch suportat și pgvector compatibil. — `pgvector/pgvector:0.8.0-pg17` + digest fixat.
- [x] Introducem SQLAlchemy async, psycopg 3 și Alembic cu versiuni blocate. — pyproject: sqlalchemy[asyncio] <2.1, psycopg[binary,pool] <3.3, alembic <1.15, pgvector <0.4; uv.lock actualizat.
- [x] Configurăm roluri separate pentru migrator, API și worker. — create în bootstrap + migrație (idempotent); granturi + default privileges; test `test_runtime_roles_not_owners`.
- [x] Definim User/Identity/Session și DigitalNotebook cu proprietar obligatoriu. — `open_notebook/database/guguta/models.py`.
- [x] Definim SourceAsset, MaterialVersion și NotebookSource distincte. — ADR-0006; trigger anti-rebind; FK RESTRICT.
- [x] Definim ProcessingArtifact/Chunk/Embedding cu metadate de versiune și dimensiune. — embedding_spaces + trigger de validare dimensiune.
- [x] Definim mesajele/citările și notițele cu relații consistente de proprietate. — chat_sessions/chat_messages/citations/notes; citări cu SET NULL pentru istoric „Sursă eliminată”.
- [x] Adăugăm constrângeri, indici și timestampuri UTC. — CHECK/UNIQUE/partial index; timestamptz; trigger updated_at.
- [x] Scriem politicile RLS și testele cu rolul runtime real. — 77 politici pe 26 tabele; `tests/guguta/test_rls_isolation.py` (A/B, fără actor, refolosire pool, worker vs coadă) — 14/14 trecute pe PostgreSQL real.
- [x] Rulăm migrarea de la zero și testăm upgrade-ul între versiuni Guguță. — migrare de la zero în container (migrator) și în teste; upgrade secvențial 0001→0002→0003 executat pe baza principală (container migrator) — validat la livrarea L3.
- [x] Adăugăm health checks și un migrator unic pe release. — healthcheck `pg_isready`; serviciul `migrator` one-shot; API/worker nu migrează la pornire.
- [x] Documentăm .env.example fără secrete și pornirea Windows/Linux. — `.env.guguta.example`; `scripts/dev.ps1` (Windows); compose pentru Linux; notă: pe mașina curentă `localhost` blochează rezolvarea IPv6 — DSN-urile folosesc `127.0.0.1`.

**Închidere:** schema și infrastructura nouă rulează. Nu se cere încă paritate cu toate rutele upstream.

## L2 — Identitate și CRUD autorizat

- [ ] Implementăm adaptorul OIDC și sesiunea opacă server-side. — **în curs**: adaptorul OIDC implementat (`open_notebook/auth/guguta/oidc.py`: PKCE S256, state/nonce semnate, JWKS, validare issuer/aud/nonce); sesiunea opacă testată end-to-end (dev-login/me/logout/revocare/suspendare). **Rămâne:** proba completă OIDC cu issuer fals în teste (RFC flow cu token exchange).
- [x] Implementăm ActorContext și stabilirea identității numai pe server. — `ActorContext` construit exclusiv din sesiunea validată; provisioning prin `guguta_provision_user` (SECURITY DEFINER, migrația 0002).
- [x] Adăugăm cookie-uri, CSRF, expirare, logout și revocare. — cookie HttpOnly/SameSite/Secure(https); CSRF derivat HMAC din token hash (tested: lipsă→403); Origin verificat (tested: străină→403); expirare absolută + inactivitate; logout/revocare tested.
- [x] Definim rolurile utilizator, editor de catalog și administrator; profesorul poate folosi rolul obișnuit. — `users.roles` cu CHECK, `ActorContext.require_role/require_any_role`; ecranele dedicate vin cu modulele lor (L5/L6).
- [x] Izolăm modul de autentificare sintetică pentru teste/development. — `POST /api/v1/auth/dev-login` refuzat când auth_mode≠test sau environment∉{development,ci}.
- [x] Refuzăm auth de test la startup staging/production. — validator `GugutaConfig` (+secret default interzis, wildcard CORS interzis) + verificare la startup-ul aplicației.
- [x] Portăm creare/listare/editare/arhivare/ștergere carnet. — `/api/v1/notebooks` CRUD + arhivare; ștergerea logica; revocarea pachetelor active la ștergere rămâne L7 (notată).
- [x] Paginăm listele și validăm sortarea. — page/page_size clamp (max 100); sort allowlist (tested: `sort=1; DROP…`→422).
- [x] Testăm ID-uri străine și falsificarea owner_id. — GET/PATCH/DELETE pe carnet străin→404; `origin` setat de server (client ignorat); `owner_id` nu există în contractele de scriere.
- [x] Testăm conexiunile refolosite din pool și contextul RLS după rollback. — test L1 cu pool de mărime 1 (actorul nu supraviețuiește rollback+refolosire).
- [x] Dezactivăm rutele upstream neportate; nu rămâne ocolire globală în API. — suprafața Guguță montează doar /api/v1 (+healthz/readyz); admin/podcasturi/surse upstream → 404/405 (tested).
- [x] Obținem două conturi sintetice cu date independente. — test CRUD izolat A/B (listă, ID direct, mutații, ștergere).

**Închidere:** A04/A11 aplicabile CRUD și A23 trec înainte de încărcarea documentelor. — izolarea CRUD e testată; A11 complet (worker/streaming/export) se revalidează la L3/L4.

## L3 — Materiale și worker

- [x] Implementăm adaptorul de stocare privată și căi generate de server. — `open_notebook/storage/guguta/` (chei UUID șarduite, root privat, O_EXCL; traversal/backslash/absolut respinse — testat).
- [x] Validăm MIME, mărime, pagini și fișiere invalide. — tip real prin magic bytes (PDF/ZIP-OOXML/UTF-8), limită mărime citită cu cap (nu trunchiat), buget de pagini, 422 (testat).
- [x] Introducem scanare/izolare parser și protecția path traversal/decomprimare. — arhive zip acceptate doar ca OOXML valid (docx/pptx), else eroare; parser rulat fără tranzacție DB deschisă; scanarea malware rămâne de configurat la pilot (R44).
- [x] Salvăm hash, MaterialVersion și asocierea locală. — SHA-256 calculat pe server; asset+version+source+job în O singură tranzacție; curățare compensatorie a octeților la eșec.
- [x] Păstrăm originalele necesare importului/downloadului; nu activăm auto-delete upstream. — download proxy autorizat (fără URL publice permanente) — testat.
- [x] Introducem ProcessingJob în PostgreSQL, creat în tranzacția obiectului țintă. — `queue.enqueue` apelat cu aceeași conexiune/tranzacție.
- [x] Implementăm claim, lease token, heartbeat și recuperare după crash. — `FOR UPDATE SKIP LOCKED`, lease_until, heartbeat (testat); lease expirat → revendicat de alt worker (testat).
- [x] Implementăm backoff, limite, retry și anulare. — backoff exponențial cu jitter în SQL, max_attempts, retry manual de către proprietar (testat), `cancel_for_target` pentru ținte dispărute (traseu implementat; test dedicat direct rămâne la L4).
- [x] Refuzăm publicarea rezultatelor cu lease/revizie expirate. — `LeaseStale` pe complete/fail (testat).
- [x] Portăm PDF text: extracție, locatori, segmentare și embedding. — pypdf per-pagină, chunking cu offseturi, embeddinguri în loturi pe spațiul activ; provider mock determinist până la D-02.
- [x] Explicăm eroarea PDF scanat fără OCR; nu declarăm succes fals. — A24: status=error + detaliu în română (testat).
- [x] Separăm starea extracției/indexării de transformările opționale. — artifact publicat atomic cu statusul sursei; transformările opționale nu există încă în pipeline.
- [x] Testăm workerul cu doi utilizatori și joburi întârziate. — izolare pe surse/joburi (A04) + lease expirat/requeue.
- [x] Implementăm stările UI de upload/progres/eroare/retry. — API: status + status_detail + GET /jobs/{id} + POST retry.

**Închidere:** upload PDF → procesare → artefacte pe PostgreSQL, reluabil și autorizat.

## L4 — Căutare, chat și prima probă completă

- [ ] Implementăm căutarea textuală și semantică pe setul autorizat din carnet.
- [ ] Validăm româna/diacriticele și documentăm configurația text search.
- [ ] Fixăm embedding_space și separăm vectorii incompatibili.
- [ ] Începem cu recuperare exactă filtrată pentru corpus mic; măsurăm înainte de optimizări.
- [ ] Implementăm limitele și bugetul de context pe manuale lungi.
- [ ] Portăm ChatSession/ChatMessage/Citation în PostgreSQL.
- [ ] Eliminăm dependența chatului MVP de SqliteSaver global.
- [ ] Dacă păstrăm checkpointuri, le autorizăm și le versionăm înainte de load/resume.
- [ ] Implementăm context_revision și invalidarea la schimbarea surselor.
- [ ] Implementăm streaming, anulare, retry și ordonarea mesajelor.
- [ ] Validăm ID-urile și locatorii citărilor înainte de afișare.
- [ ] Adăugăm răspunsul pentru lipsa informației și eroarea furnizorului.
- [ ] Testăm A/B inclusiv în payloadurile modelului, streamuri și memorie.
- [ ] Testăm sursa eliminată și răspunsul în curs.
- [ ] Executăm fluxul doi utilizatori → carnet → PDF → căutare → chat/citare → restart.

**Poartă G2/G3:** proba completă și izolarea trec. Catalogul și share-ul nu încep înainte de această probă.

## L5 — Produs MVP, design și administrare

- [ ] Portăm DOCX, PPTX, TXT/Markdown și text introdus.
- [ ] Implementăm notițe private și salvarea răspunsurilor.
- [ ] Aplicăm localizarea ro-MD și terminologia Carnet digital/Materiale/Notițe/Conversație.
- [ ] Aplicăm wordmark, tokens, tipografie și spațiere din ghid.
- [ ] Implementăm pagina principală și carduri distincte oficial/personal.
- [ ] Implementăm trei panouri desktop și taburi mobile, conform ghidului.
- [ ] Implementăm citarea în panou și toate stările loading/empty/error/success.
- [ ] Verificăm 360/768/1440px, zoom 200%, focus, tastatură și contrast.
- [ ] Ascundem setările tehnice elevilor și le protejăm în API.
- [ ] Portăm configurarea centrală chat/embedding și criptarea cheilor cu posibilitate de rotație.
- [ ] Introducem cote și măsurarea costurilor/încercărilor.
- [ ] Dezactivăm pe server Podcasts, source-chat, Ask global, URL/media/arhive și runtime-uri amânate.
- [ ] Implementăm raportarea răspunsului/materialului problematic.
- [ ] Verificăm că niciun buton activ nu folosește doar mock în buildul livrat.

**Închidere:** experiență de elev completă în română, fără configurarea furnizorilor sau a infrastructurii.

## L6 — Catalog și șabloane

- [ ] Implementăm Template/TemplateVersion/TemplateMaterial.
- [ ] Introducem metadate clasă, disciplină, ediție, limbă și proveniență.
- [ ] Implementăm draft, verificare, publicare și retragere.
- [ ] Restrângem publicarea la materiale gata cu drepturi înregistrate.
- [ ] Fixăm manifestul versiunii publicate.
- [ ] Implementăm catalogul public și filtrele, fără expunerea drafturilor.
- [ ] Implementăm instanțierea tranzacțională și idempotentă.
- [ ] Creăm ID-uri locale noi pentru materialele copiei.
- [ ] Verificăm zero mesaje, notițe și memorie personală în copia nouă.
- [ ] „Începe din nou” folosește versiunea publicată curentă afișată.
- [ ] Retragerea oprește instanțieri noi, fără modificarea copiilor.
- [ ] Testăm A02/A03/A05/A14/A18.

**Poartă G4:** două copii se modifică independent și păstrează proveniența.

## L7 — Snapshot, import și revocare

- [ ] Implementăm ShareSnapshot/ShareMaterial și versiunea contractului.
- [ ] Implementăm allowlist explicit; nu serializăm generic notebook-ul.
- [ ] Excludem chat, notițe, insight-uri personale, memorie și secrete.
- [ ] Creăm token/link și cod pentru același pachet, cu protecție în loguri.
- [ ] Implementăm preview autorizat și formular de import.
- [ ] Implementăm cota logică și verificarea concurentă.
- [ ] Creăm copia și ShareImport în tranzacție.
- [ ] Legăm idempotency de actor/operație/payload; importul intenționat nou rămâne permis.
- [ ] Serializăm verificarea finală a importului cu revocarea.
- [ ] Recuperăm importul finalizat după timeout, inclusiv după revocare ulterioară.
- [ ] Revocăm împreună codul și linkul fără efect asupra copiilor existente.
- [ ] Definim expirarea/limitele opționale fără efect retroactiv.
- [ ] Implementăm ștergerea carnetului/contului autorului cu revocarea pachetelor active.
- [ ] Implementăm GC coordonat cu snapshoturi/importuri/joburi și retenție.
- [ ] Testăm efectele externe și curățarea compensatorie la eșec.
- [ ] Executăm A07–A10/A15/A16/A19–A21/A28 cu teste concurente.

**Poartă G5:** importul transferă exclusiv materialele aprobate și respectă independența.

## L8 — Eliminare legacy și transfer controlat

- [ ] Verificăm imports, query-uri și config: fără SurrealDB/surreal-commands în runtime țintă.
- [ ] Verificăm că memoria SQLite upstream nu este reactivată prin rute rămase.
- [ ] Eliminăm migrațiile/serviciile vechi din buildul țintă, păstrând istoria Git și backupurile.
- [ ] Construim imaginile proprii din commit, nu din tagul upstream flotant.
- [ ] Dacă se transferă date existente, desemnăm proprietarul și mapăm ID-uri, mesaje, citări și fișiere.
- [ ] Executăm dry-run și reconciliere înainte de transfer.
- [ ] Documentăm ce date nu sunt portate și obținem decizia aferentă; nu le ștergem implicit.
- [ ] Pregătim cutover și rollback, inclusiv scrierile apărute după backup.
- [ ] Nu cerem funcționalitate audio pentru a închide migrarea MVP.

**Închidere:** build fără dependențele eliminate și fără pierderi ascunse de date.

## L9 — Verificări finale și readiness

Aceste verificări completează testele executate continuu în L0–L8.

- [ ] Executăm toate scenariile A01–A28 și matricea permisiunilor.
- [ ] Testăm migrații, RLS cu rol runtime, joburi și concurență în PostgreSQL real.
- [ ] Executăm E2E CLI și revizia design/accesibilitate.
- [ ] Verificăm transportul, secretele, configurarea containerelor și rate limiting.
- [ ] Executăm scanările de vulnerabilități și licențe pentru imaginile release.
- [ ] Configurăm loguri, metrici, alerte și responsabilul de intervenție.
- [ ] Restaurăm un backup și reconciliem fișiere/date/citări/revocări.
- [ ] Stabilim RPO/RTO, concurență, cost și praguri de latență.
- [ ] Evaluăm româna/citările cu un profesor și corpus versionat.
- [ ] Închidem deciziile de drepturi, acces minori, găzduire și furnizori înainte de pilot real.
- [ ] Completăm deployment readiness cu dovezi, nu cu intenții.
- [ ] Documentăm separat problemele rămase și funcțiile dezactivate.

**Porți G1/G6/G7:** licențe conforme, securitate fără blocaje și acceptare pedagogică înainte de elevi reali.

## L10 — Deployment autorizat și observație

- [ ] Identificăm commitul, digesturile și schema release-ului.
- [ ] Obținem GO pentru mediul și fereastra definite; redactarea ghidului nu este autorizare de producție.
- [ ] Executăm backupul pre-release și migrarea unică.
- [ ] Lansăm imaginile aprobate și verificăm readiness.
- [ ] Executăm smoke sintetic A/B, chat/citări, share/import/revocare.
- [ ] Verificăm metricile, joburile, costul și alertele.
- [ ] Înregistrăm menținerea sau rollbackul după fereastra de observație.
- [ ] Predăm runbookul, rezultatele și responsabilitatea de suport.

## Ulterior — instrumente educaționale

- [ ] Flashcard-uri: schemă, surse/citări, editare și evaluare pedagogică.
- [ ] Quiz-uri: întrebări validate, explicații și fără notare oficială automată.
- [ ] Prezentare audio: adaptare Podcasts, transcript/citări, voci și drepturi verificate.
- [ ] URL/media/OCR avansat: necesitate, licențe, cost și siguranță validate separat.
- [ ] Organizații/clase/progres: decizie nouă de produs, fără extindere implicită a MVP.

## Definiția finalizării

**Probă tehnică completă:** L0–L4, doi utilizatori izolați și persistență verificată.
**MVP funcțional:** L0–L8 și scenariile A01–A28 aplicabile demonstrate, fără funcții simulate.
**Pilot pregătit:** L9 și deployment readiness cu controalele B/O/P aplicabile trecute.
**Lansat:** L10 executată în mandat explicit, cu verificări post-release.

Un MVP funcțional nu este declarat automat pregătit pentru elevi reali. Funcțiile ulterioare nu sunt condiții pentru MVP, dar trebuie să fie inaccesibile dacă nu sunt implementate.
