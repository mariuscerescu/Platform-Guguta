# Audit de implementare — Platforma Guguță

Data: 6 septembrie 2026. Ramura: `guguta/foundation`.
Commit auditat: `64732f5f67de0a8ae80a4bd9592529467b749c48`.

## 1. Verdict

**NO-GO pentru pilot cu elevi reali sau producție. Implementare parțială, cu o fundație reutilizabilă, dar cu blocaje tehnice în autentificare, interfață, chat și worker.** Finalizarea workerului de implementare nu echivalează cu finalizarea MVP-ului.

PostgreSQL, migrațiile, separarea suprafeței API Guguță, modelul de copii și testele de izolare reprezintă progres real. Recomand continuarea acestui cod, cu remediere prioritară și teste de regresie; nu recomand o nouă rescriere.

Checklistul de implementare bifează unele cerințe acoperite doar de funcții interne, simulări sau teste secvențiale. Raportul L9 afirmă că blocajele rămase sunt decizii umane; auditul infirmă această concluzie. Există defecte remediabile de echipa tehnică fără alte decizii de produs.

Documentația canonică este acum în `docs/guguta/`, conform [README](README.md). Copiile din directorul părinte reprezintă documentația de dinaintea implementării.

## 2. Metodă, rezultate și limite

Am comparat codul cu [specificațiile](SPECIFICATII_GUGUTA.md), [ghidul](GHID_IMPLEMENTARE_LLM.md), [checklistul implementării](GUGUTA_IMPLEMENTATION_CHECKLIST.md), ADR-urile, rapoartele L0–L9 și [readiness](DEPLOYMENT_READINESS_CHECKLIST.md). Am inspectat API, servicii, migrații/politici RLS, autentificare, stocare, parsare, joburi, căutare/chat, frontend, Docker și CI.

| Verificare executată | Rezultat și interpretare |
| --- | --- |
| Ruff, comanda pachetului Guguță din CI | PASS. Atenție: lista nu include jobs/storage/ai Guguță; vezi F21. |
| Mypy, comanda pachetului Guguță din CI | PASS, 32 fișiere. Aceeași limitare de acoperire. |
| Ruff și mypy suplimentar pe jobs/storage/ai Guguță | PASS; mypy: încă 12 fișiere. Auditul le-a verificat, dar CI trebuie completat în continuare. |
| Testele existente `tests/guguta`, fără A22 restore | **60 passed**, 27,87 s, PostgreSQL real izolat. |
| Prima rulare a suitei | 59 passed, un setup error din permisiunile directorului temporar Windows; rezolvat prin `--basetemp` în workspace, apoi suita a trecut. Nu este defect al aplicației. |
| Cinci probe independente de audit | **5 passed**: aserțiunile confirmă existența a cinci defecte, nu conformitatea produsului. |
| `frontend-guguta`: `npm run build` | PASS, Next.js instalat 15.5.25. Build-ul nu demonstrează funcționarea fluxurilor UI. |
| `frontend-guguta`: `npm run lint` | FAIL ca verificare neinteractivă: solicită configurarea ESLint. |
| Inventar Docker, numai citire | API/worker/DB Guguță porniți; niciun container frontend Guguță în lista observată. Demo-ul upstream era încă pornit. |

Suita a rulat pe containerul temporar `guguta-audit-db-20260906`, port local 55434, separat de DB aplicației de pe 5433. Fixture-ul recreează `guguta_test` și schimbă parolele rolurilor pe serverul selectat, motiv pentru care nu l-am rulat pe serverul existent. Containerul temporar a fost oprit și eliminat după audit; comenzile de reproducere necesită pornirea din nou a unui server temporar.

Nu am executat `test_a22_restore.py`: acesta folosește explicit containerul existent `guguta-db-1`, indiferent de serverul selectat prin DSN. Nu am modificat volumele aplicației sau codul funcțional. Am adăugat doar acest raport și [probele auditului](audit-2026-09-06/test_probes.py).

Nu am folosit Computer Use. Nu am executat o sesiune de browser/E2E, un audit vizual, un test de încărcare, un scan complet de vulnerabilități/dependențe, o evaluare cu modele reale sau restaurarea infrastructurii. Constatările UI sunt bazate pe cod și build. „Audit complet” în acest raport înseamnă acoperirea componentelor și cerințelor disponibile, nu certificarea absenței oricărei vulnerabilități.

## 3. Priorități și tipuri de dovezi

- **P1:** blochează fluxul principal, integritatea/confidențialitatea sau lansarea; remediere înainte de pilot.
- **P2:** defect important de corectitudine, exploatare sau operare; remediere înainte de acceptanța componentei.
- **Reprodus:** probă executată în audit. **Cod:** traseu identificat în cod, fără reproducerea completă a condiției concurente/în browser. **Lipsă:** funcționalitatea cerută nu este prezentă în suprafața inspectată.

Nu atribui P0: nu am demonstrat un incident activ sau o exfiltrare generală a datelor utilizatorilor.

## 4. Constatări și instrucțiuni de remediere

### F01 — P1 — OIDC pierde cookie-urile la redirect

**Dovadă: reprodus pentru login; cod pentru callback.** `api/routers/guguta_v1.py:111–117` setează cookie-ul state pe parametrul `response`, dar returnează alt `RedirectResponse`. Același defect apare la callback, liniile 147–150, pentru cookie-ul sesiunii și headerul CSRF. Proba `test_oidc_redirect_loses_state_cookie` obține 307 fără `Set-Cookie`.

**Impact:** browserul nu poate finaliza autentificarea reală. Testele din `test_oidc_flow.py` apelează direct `OidcClient`, nu rutele HTTP, deci nu detectează defectul.

**Remediere:** construiți obiectul de redirect, setați cookie-urile pe el și returnați același obiect. Test HTTP complet cu cookie jar: login → issuer fals → callback → `/auth/me` → mutație CSRF → logout. Documentația [FastAPI despre cookie-uri și răspunsuri directe](https://fastapi.tiangolo.com/advanced/response-cookies/) confirmă această distincție.

### F02 — P1 — Sesiunea frontend depinde de un CSRF salvat numai la login sintetic

**Dovadă: cod.** `frontend-guguta/app/page.tsx:21` decide autentificarea din `localStorage`. `lib/api.ts` salvează tokenul doar în `loginDev`; `/auth/me` nu îl furnizează. Headerul unui redirect OIDC nu ajunge automat în localStorage. Chiar după F01, utilizatorul OIDC este trimis înapoi la login sau nu poate efectua mutații.

**Remediere:** determinați sesiunea printr-un endpoint autentificat, care oferă și bootstrap CSRF sigur; tratați explicit expirarea și logout-ul. Nu folosiți existența localStorage drept dovadă de autentificare. Folosiți `authorization_endpoint` din discovery: `oidc.py:111` presupune în prezent `<issuer>/authorize`, incompatibil cu furnizori care publică alt traseu. Ascundeți login-ul sintetic în configurația publică.

**Acceptare:** OIDC funcționează din profil nou de browser și după ștergerea localStorage, cu issuer al cărui authorization endpoint nu este `/authorize`.

### F03 — P1 — Pe mobil toate cele trei panouri sunt invizibile

**Dovadă: cod.** În `frontend-guguta/app/globals.css`, sub 1024px `.pane` are `display:none`, iar numai `.pane.active` se afișează. În `app/notebook/[id]/page.tsx:231,300,353`, toate secțiunile au permanent `className="pane"`; `setTab` schimbă doar starea/butonul.

**Remediere:** legați explicit panoul activ de tab, implementați relația tab/tabpanel și navigarea cu tastatura. Respectați pragurile ghidului: desktop >=1280, intermediar 768–1279, mobil <768. **Acceptare:** teste la 360/768/1440px care verifică vizibilitatea și utilizarea efectivă a fiecărui panou, inclusiv zoom 200%.

### F04 — P1 — Frontendul livrat nu acoperă fluxurile MVP

**Dovadă: lipsă în cele patru rute construite.** Pagina carnetului permite numai adăugare text. Lipsesc uploadul de fișiere, previzualizarea/downloadul din UI, crearea și revocarea partajării, editarea/ștergerea/arhivarea carnetului, selectorul conversațiilor existente, editarea notițelor/salvarea răspunsului, raportarea conținutului și administrarea catalogului. API-uri pentru o parte dintre acestea există, dar nu reprezintă experiență de elev completă.

Progresul surselor nu este urmărit prin polling/SSE după încărcare; UI poate rămâne la starea inițială până la reîncărcare. Citările sunt text și JSON de locatori, fără navigare la fragment. Enter nu verifică `sending` sau compoziția IME, deși butonul este dezactivat; poate trimite cereri suplimentare.

**Remediere:** implementați fluxurile din §9 al ghidului, cu loading/error/retry, confirmare la ștergere, focus și mesaje accesibile. Test E2E pentru fiecare operație, nu doar pentru existența endpointului.

### F05 — P1 — Linkul de partajare generat nu poate fi folosit în interfață

**Dovadă: cod/build.** `sharing.py:158` întoarce `/import#token=...`, dar build-ul nu are ruta `/import`. Formularul din homepage trimite șirul integral; `_resolve_snapshot` doar aplică hash după `strip()`, fără extragerea tokenului din link. Introducerea unui link complet nu este echivalentă cu introducerea tokenului. Preview-ul API nu este apelat de formular.

**Remediere:** implementați ruta de import, extragerea controlată a fragmentului și păstrarea intenției după login; acceptați și codul. Afișați manifestul înainte de confirmare. Testați exact linkul returnat de API, cu utilizator neautentificat inițial, și separat codul.

### F06 — P1 — Catalogul nu este vizibil vizitatorului

**Dovadă: cod.** Homepage face return înainte de fetch-ul catalogului dacă lipsește CSRF și redirecționează la login. API-ul public adăugat pentru A01 nu rezolvă acest comportament UI.

**Remediere:** încărcați catalogul independent de sesiune; autentificarea este cerută la creare/import. Test de acceptare A01 prin pagina principală fără cookie, cu draft și versiune publicată.

### F07 — P1 — Istoricul reintroduce conținutul surselor eliminate

**Dovadă: reprodus.** `api/services/guguta/chat.py:263–274` citește ultimele mesaje fără filtrare după `context_revision`. Proba `test_removed_source_history_still_sent` elimină o sursă, păstrează alta și observă `SECRET_OLD_AUDIT` în istoricul trimis furnizorului la întrebarea următoare.

**Impact:** încălcare directă A17; actualizarea reviziei și filtrarea retrievalului sunt insuficiente.

**Remediere:** istoricul vizibil rămâne, dar contextul modelului se reconstruiește conform reviziei curente; tratați inclusiv rezumatele, cache-ul și întrebările vechi. Testați payloadul efectiv primit de provider după deselectare, ștergere și înlocuire.

### F08 — P1 — Răspunsurile în curs nu sunt invalidate; ordonarea concurentă este incompletă

**Dovadă: cod.** Faza 3 din `chat.py:317` nu reverifică revizia carnetului sau selecția surselor. Lock-ul sesiunii din faza 1 este eliberat înainte de generare; `MAX(seq)+1` pentru răspunsul asistentului se calculează fără lock în faza 3. Două cereri pot interfera sau încălca unicitatea secvenței. Nu există implementare SSE/anulare în rutele Guguță.

**Remediere:** stare persistentă de generare legată de revizie și mesaj, claim/idempotency atomic, ordonare tranzacțională și verificarea reviziei înaintea publicării. Implementați anularea și streamul cu validarea continuă cerută în ghid.

**Acceptare:** provider lent controlat; modificați selecția în timpul generării; niciun rezultat invalid nu este publicat. Două trimiteri simultane au comportament explicit și ordine stabilă.

### F09 — P1 — Retry după eroarea furnizorului rămâne permanent pending

**Dovadă: reprodus.** `chat.py:300` persistă idempotency `pending`; la excepția providerului returnează 502 fără tranziție de stare. Retry cu aceeași cheie primește mereu `pending` din linia 403. Proba dedicată confirmă.

**Remediere:** stări failed/retryable, recuperarea operațiilor abandonate și termen-limită; păstrați semantica aceleiași operații fără duplicarea mesajului elevului. Test: provider eșuează o dată, apoi reușește; aceeași cheie finalizează o singură operație.

### F10 — P1 — Workerul publică înainte să verifice lease-ul

**Dovadă: reprodus.** `jobs/guguta/handlers.py:146–203` comite artefactele și starea `ready`, apoi apelează `complete` separat. Proba schimbă lease tokenul după claim; handlerul vechi publică totuși sursa ca `ready`. Refuzul final nu inversează publicarea. Și `_mark_source_error` scrie fără fencing.

**Remediere:** în aceeași tranzacție cu publicarea, blocați/verificați jobul, lease token, expirarea și revizia reală a țintei, apoi publicați și finalizați. Fencing și pentru erori. Testele existente ale funcției `complete` nu înlocuiesc testul handlerului complet.

### F11 — P1 — Controalele cozii sunt declarate, dar nu aplicate complet

**Dovadă: cod.** `queue.py:claim` nu filtrează `attempts < max_attempts` sau `deadline`; crash-urile repetate pot fi revendicate nelimitat. Funcția heartbeat există, dar workerul/handlerul nu o apelează în timpul lucrului. `max_concurrent_jobs_per_user` nu este aplicat la claim. `complete` compară revizia cu valoarea jobului, nu verifică versiunea actuală a materialului și nici `lease_until > now()`.

**Remediere:** implementați limitele în protocolul real de execuție, heartbeat periodic și recuperare bounded; evitați blocarea event loop-ului în parsare/embedding. Testați doi workeri și un proces omorât după claim, depășirea deadline-ului și epuizarea încercărilor.

### F12 — P1 — Revocarea/importul nu au serializarea afirmată

**Dovadă: cod și analiză tranzacțională; cursa nu a fost executată în audit.** `sharing.py:493` face un SELECT final, dar nu ține un lock comun cu revocarea până la commit. Revocarea poate comite între acel SELECT și commitul importului. `catalog.py:instantiate` folosește aceeași presupunere pentru retragere. Un SELECT repetat nu este serializare.

**Remediere:** protocol comun de lock tranzacțional, inclusiv pentru importatori cu RLS, sau izolare și retry care demonstrează ordinea cerută. Nu deschideți UPDATE generic asupra snapshoturilor străine pentru a permite lock-ul. [PostgreSQL explică blocările explicite și durata lor](https://www.postgresql.org/docs/17/explicit-locking.html).

**Acceptare:** test cu bariere exact între ultima verificare și commit, pentru ambele ordini, atât la revoke/import, cât și la retire/instantiate.

### F13 — P1 — Cotele pot fi ocolite; idempotency concurentă nu este completă

**Dovadă: cod.** `sources.py:_create_source` verifică bytes și numărul de surse fără lock comun pe utilizator/carnet. Importul blochează utilizatorul, dar uploadul nu participă la același protocol. Instanțierea din catalog nu verifică deloc cota logică. Copierea repetată a șabloanelor o poate depăși.

În import/instantiate/chat, lookup-ul idempotency este înaintea tranzacției de scriere; două cereri simultane pot trece de lookup și a doua poate primi conflict SQL în locul rezultatului deja creat. Constrângerea UNIQUE previne dublarea unor înregistrări, nu oferă singură contractul HTTP de replay.

**Remediere:** rezervare/lock și reverificare atomică pentru toate căile de creare; aceeași cheie cu același payload returnează rezultatul, alt payload returnează 409. Frontendul trebuie să păstreze cheia unei operații la retry, nu să genereze alta la fiecare apăsare.

### F14 — P1 — Configurația production acceptă secrete nesigure și simulări

**Dovadă: reprodus.** `database/guguta/config.py` acceptă `environment=production`, `server_secret=""`, cheia implicită de criptare, chat mock, hash embeddings și origini HTTP dacă celelalte câmpuri obligatorii sunt prezente. Validatorul verifică doar egalitatea secretului de sesiune cu o singură valoare implicită; nu validează cheile de criptare, HTTPS sau redirect URI complet.

Tot aici API/worker sunt obligați să aibă DSN de migrator în production, deși nu îl folosesc; separarea secretelor pe roluri trebuie păstrată.

**Remediere:** validare per proces, fail-closed pentru secrete goale/implicite, chei valide, HTTPS public și OIDC complet. Interziceți providerii mock/hash în mediile cu utilizatori reali. Teste negative de startup pentru fiecare caz și verificarea lipsei secretului migratorului în runtime.

### F15 — P1 — AI real nu este implementat; limitele nu sunt conectate

**Dovadă: lipsă/cod.** Factory-urile acceptă numai `MockChatProvider` și `HashEmbeddingProvider`. Acesta din urmă nu este model semantic. Credencialele administrative nu sunt conectate la un provider real. `SYSTEM_PROMPT` există, dar nu este folosit de mock. Nu putem considera A12/A13/A25 evaluate pedagogic prin răspunsuri deterministe.

`chat_total_timeout_seconds` nu este aplicat la generare; providerul este sincron în funcția async. Embeddingul întrebării se execută cu tranzacția de căutare deschisă. `_budget` taie contextul fără metadata/avertizare, istoricul nu are buget de tokeni, costul este fix 0. Nu există rate limiting aplicat rutelor costisitoare sau încercărilor de cod.

**Remediere:** adaptor AI real configurabil, asincron sau izolat corect, timeouts/cancel, retry controlat, rate limits și usage real; apelați providerii în afara tranzacțiilor. Expuneți limitările contextului elevului. Alegerea furnizorului poate cere decizie, implementarea contractului și a protecțiilor nu.

### F16 — P2 — Căutarea vectorială inversează relevanța și ignoră starea sursei

**Dovadă: cod.** SQL ordonează corect distanța cosine ascendent, dar `search.py:175` reordonează toate rezultatele folosind `-c.score`; pentru vectori score este distanța, astfel fragmentele mai îndepărtate ajung înaintea celor apropiate. Query-urile nu cer `ns.status='ready'` și versiunea de artefact eligibilă, doar selecția (și spațiul activ pentru vectori).

**Remediere:** normalizați scorul sau sortați distanțele ascendent, definiți fusion explicit și filtrați starea/versionarea. Test cu distanțe cunoscute și surse deselectate, în eroare sau în reprocesare. Pentru A27 implementați și construirea/validarea/activarea noului index, nu doar respingerea unui model diferit.

### F17 — P1 — Uploadul și parsarea nu au limite complete de resurse

**Dovadă: cod.** Aplicația Guguță nu montează o limită globală de request înaintea parsării multipart; `_read_upload` limitează lectura ulterioară, nu corpul deja primit/spooled. `detect_kind` și numărarea paginilor PDF rulează înainte de verificarea proprietății carnetului. OOXML se decomprimă integral, fără buget de bytes dezarhivați/raport/număr de intrări. Parsarea este sincronă, fără deadline/proces izolat.

**Remediere:** limite la proxy și ASGI inclusiv pentru request fără Content-Length, autorizare timpurie, streaming bounded, limite OOXML și extracție, proces de parsare cu CPU/memorie/timp controlate. Teste benigne de depășire a limitelor, fără payloaduri distructive. Nu considerați limita de 25MiB o protecție suficientă împotriva expansiunii documentului.

### F18 — P2 — Garbage collection nu gestionează ciclul real al materialelor

**Dovadă: cod.** `jobs/guguta/gc.py` colectează numai assets fără niciun `material_version`. Ștergerea sursei/carnetului păstrează versiunile; nu există traseu de colectare a versiunilor orfane, deci fișierele normale eliminate nu ajung candidate. După ștergerea rândurilor, un eșec `storage.delete` lasă fișierul fără înregistrare persistentă pentru retry. Nu există apel operațional/scheduler al GC în workerul inspectat.

**Remediere:** graf complet de referințe (copii, snapshoturi, template-uri, joburi, retenție), tombstone/outbox pentru ștergerea bytes și retry durabil; privilegii de mentenanță dedicate. Testați upload real → ștergere ultima referință → retenție → GC, plus eșec de stocare și reluare. Păstrați explicit copiile existente.

### F19 — P1 — Configurația Docker implicită blochează mutațiile frontendului

**Dovadă: cod/configurație; fără test în browser.** Frontendul este publicat pe `localhost:3001`; API păstrează originul permis implicit `http://localhost:3000`. Browserul trimite Origin 3001 prin proxy, iar middleware îl respinge după login. `next.config.ts` local cade pe 5055, care în inventarul actual este demo-ul upstream, în timp ce API Guguță este pe 5056.

**Remediere:** configurație coerentă a originului public/proxy/porturilor pentru fiecare mod, în exemple și scripturi. Testați un login și un POST real prin frontendul pornit exact cu Compose, nu direct pe ASGI cu origin artificial 3000.

### F20 — P1 — Runbook-ul poate selecta stiva greșită; release-ul nu este reproductibil

**Dovadă: cod.** `RUNBOOK_CUTOVER.md` omite `-f docker-compose.guguta.yml`; în rădăcina repo există `docker-compose.yml` upstream. Numele proiectului nu selectează fișierul. Runbook-ul referă `scripts/backup.ps1` și `scripts/smoke.ps1`, inexistente; există `smoke.py`. Frontendul lipsește din pașii de pornire.

Imaginile API/migrator instalează intervale de versiuni, nu un lock al stivei țintă; frontend Docker folosește `npm install`, iar imaginile de bază nu sunt fixate prin digest. Același commit poate produce alte dependențe. Compose pentru DB nu transmite `GUGUTA_PG_API_PASSWORD`/`WORKER_PASSWORD` către scriptul bootstrap; parole personalizate în `.env` pot da runtime DSN diferit de parola creată.

**Remediere:** manifest release explicit, toate comenzile cu fișierul corect, imagini API/worker/frontend/migrator din aceeași revizie, lock-uri/digests și `npm ci`; bootstrap sigur și parametrizat. Nu interpolați parola direct în SQL fără quoting. Executați runbook-ul pe mediu gol dedicat și documentați backup/restore/rollback real.

### F21 — P2 — CI nu verifică componente importante din produsul livrat

**Dovadă: cod și lint executat.** `guguta-ci.yml` nu are job frontend, build de imagini sau E2E. Ruff/mypy omit `open_notebook/jobs/guguta`, `storage/guguta` și `ai/guguta`. `scripts/check.ps1` construiește `frontend`, nu `frontend-guguta`. Noul frontend nu are lint configurat neinteractiv, script de teste, E2E sau accesibilitate automate.

**Remediere:** pipeline pentru exact runtime-ul livrat: lint/typecheck integral, unit/integration cu PG, frontend lint/typecheck/tests/build, E2E, smoke imagini, scan secrete/dependențe și licențe. Un build verde nu este dovadă de funcționare mobil/OIDC/share.

### F22 — P2 — Restaurarea A22 și acoperirea acceptanței sunt supraevaluate

**Dovadă: cod/teste/rapoarte.** A22 încarcă text în DB și restaurează numai SQL; nu recuperează bytes din storage și nu verifică un download autorizat după restore. Hardcodează `guguta-db-1`; în CI, serviciul PostgreSQL nu are acel nume și testul poate fi sărit. Asistența semantică A12, A13 și A25 este testată prin mock. Testele de sharing nu conțin reproducerea cu bariere a cursei finale din F12.

**Remediere:** fixture de infrastructură explicită, restore DB + fișiere + chei/config necesare într-un mediu separat, verificare prin rolurile runtime. În CI, lipsa unei infrastructuri obligatorii trebuie să eșueze, nu să pară acceptare. Distingeți `PASS API`, `PASS E2E`, `PASS mock`, `PASS real`, `parțial`, `neexecutat`.

### F23 — P2 — Publicarea nu verifică drepturile; ștergerea contului nu este implementată

**Dovadă: cod/lipsă.** `catalog.py:publish_version` verifică artefactele complete, nu `rights_note` sau drepturile fiecărui material. Câmpul este opțional. `revoke_all_for_author` este un helper, nu un flux de ștergere a contului cu revocarea sesiunilor, retenție și păstrarea copiilor. Testul etichetat A28 șterge carnetul, nu contul.

**Remediere:** validări de publicare și metadate de proveniență/drepturi la nivelul cerut; operație controlată de ștergere/suspendare cont, fără ștergerea copiilor destinatarilor. Testați exact A28. Aceasta este verificarea contractului de produs, nu o concluzie juridică despre manuale.

### F24 — P2 — Downloadul construiește nesigur numele din header

**Dovadă: cod.** `api/routers/guguta_v1.py:346` interpolează numele original direct în `Content-Disposition`. Nume cu diacritice în afara Latin-1, de exemplu `Științe.pdf`, pot eșua la codificarea headerului; ghilimelele și caracterele de control nu sunt normalizate.

**Remediere:** generator standard de Content-Disposition cu fallback ASCII și `filename*` UTF-8, fără CR/LF/ghilimele neescapate. Test cu nume românești și caractere rezervate. Nu am demonstrat exploatarea unui response splitting în serverul HTTP real.

### F25 — P2 — Operarea și observabilitatea nu sunt încă pregătite pentru release

**Dovadă: cod/lipsă.** `/readyz` verifică existența unei versiuni de schemă, nu compatibilitatea cu release-ul sau accesul storage. `request_id` este preluat de la client ori `-`, fără generare server. Runbook-ul menționează alerte și backup, dar nu livrează configurarea și probele lor. Nu există dovadă de scanare a dependențelor/imaginilor finale sau inventar complet de licențe.

**Remediere:** readiness pentru dependențele necesare, metrici separate pentru worker/AI, request ID server, loguri sanitizate, alerte cu exercițiu, backup programat și restaurare, SBOM/licențe și scanări pe imaginile finale. API-ul poate rămâne disponibil când AI este indisponibil, cu eroare controlată; liveness nu trebuie legat de sănătatea furnizorului AI.

## 5. Ce păstrăm

- Suprafața separată `api.guguta_app`, care nu montează rutele legacy amânate.
- PostgreSQL/Alembic/pgvector, roluri runtime separate și context RLS tranzacțional. Testele de izolare executate au trecut; nu am demonstrat acces HTTP între utilizatori în acele scenarii.
- Modelul cu asocieri locale noi peste materiale/versionări comune și contractul de snapshot fără chat/notițe.
- Hash-urile pentru credențialele de partajare, sesiuni opace și verificarea permisiunilor administrative.
- Parsarea cu locatori și eroarea explicită pentru PDF scanat fără text utilizabil.
- Tokenurile vizuale, terminologia română și separarea conceptuală materiale/conversație/notițe, completate prin remedierea fluxurilor UI.
- Păstrarea separată a datelor upstream și absența cerinței de a implementa podcasturi înaintea MVP-ului.

## 6. Situația criteriilor A01–A28

„Parțial” nu înseamnă că tot criteriul este defect; înseamnă că nu există încă dovada completă cerută de contract.

| Criterii | Situație după audit |
| --- | --- |
| A01 | API public testat; UI vizitator neconform — F06. |
| A02–A06 | Baza API de creare/copiere/independență testată; fluxurile UI, cote și concurență necesită completare — F04/F13. |
| A07–A10 | Snapshot/token/cod/revocare secvențială au teste; linkul real în UI este nefuncțional — F05. |
| A11 | Izolare backend demonstrată în scenariile existente; streaming/export/alte suprafețe inexistente nu pot fi declarate testate. |
| A12–A13 | Citări/mecanism mock parțial; navigarea la sursă și evaluarea semantică reală lipsesc — F04/F15. |
| A14 | Versionarea copiilor testată; retragerea concurentă necesită F12. |
| A15 | Replay secvențial testat; concurență și retry UI incomplete — F09/F13. |
| A16 | Tranzacții/erori de bază testate; retry permanent pending și cleanup incomplet — F09/F18. |
| A17 | **Neconform, reprodus** — F07; invalidarea generării lipsește — F08. |
| A18 | Păstrarea referințelor testată; lifecycle/GC incomplet — F18. |
| A19 | Nedemonstrat corect în cursa finală; protocol incomplet — F12. |
| A20 | Cota importului are lock; căile alternative/concurente nu aplică același protocol — F13. |
| A21 | Snapshot fixat testat; **fencing neconform, reprodus** — F10/F11. |
| A22 | Restore SQL parțial raportat anterior; restore storage+runtime neexecutat în audit și neacoperit de test — F22. |
| A23 | Refuzurile administrative existente au trecut testele; nu echivalează cu pentest exhaustiv. |
| A24 | Scan fără text: testele existente au trecut. |
| A25 | Probe deterministe fără provider real; evaluare limitată — F15/F22. |
| A26 | Eroare 502 testată; timeout/buget/retry incomplete — F09/F15. |
| A27 | Refuzul spațiului incompatibil există; migrarea integrală a indexului și activarea verificată lipsesc — F16. |
| A28 | Ștergerea carnetului testată, ștergerea contului nu — F23. |

## 7. Ordinea recomandată pentru workerul de remediere

1. **Corectați raportarea progresului:** redeschideți bifele afectate; nu schimbați specificațiile doar ca să corespundă codului existent.
2. **Autentificare și pornire:** F01/F02/F14/F19; test HTTP și browser cu issuer fals, fără date reale.
3. **Integritate chat/worker:** F07–F13; teste cu bariere concurente și fault injection înainte de cod, apoi integrare reală PG.
4. **Fluxuri de produs:** F03–F06/F24; upload, citări, share/import/revoke, mobil și catalog vizitator, demonstrabile prin E2E.
5. **AI și resurse:** F15–F17; provider real, timeout, rate limits, index nou și evaluare română după alegerea providerului.
6. **Date și operațiuni:** F18/F20/F22/F23/F25; GC, conturi, release reproductibil, backup/restore și runbook executabil.
7. **CI final:** F21; toate verificările pe exact aplicația și imaginile ce urmează să fie livrate.

Pentru fiecare Fxx: commit/revizie, ce s-a schimbat, test de regresie, rezultatul executat și limita rămasă. Nu marcați rezolvat pe baza unei explicații, a unui helper neapelat sau a unui test care nu parcurge ruta reală.

## 8. Checklist de reacceptare

- [ ] F01–F25 au rezoluție și dovezi legate de commit; toate P1 închise înainte de pilot.
- [ ] Cele cinci probe de audit sunt transformate în teste care cer comportamentul corect. Atenție: probele actuale trec când defectul există.
- [ ] Login OIDC complet, CSRF și logout funcționează prin frontend/proxy, cu profil nou de browser.
- [ ] Fluxul vizitator → șablon → carnet → PDF → procesare → întrebare → citare funcționează.
- [ ] Linkul generat și codul ajung prin preview la o copie independentă, fără chat/notițe.
- [ ] Chatul nu reutilizează surse eliminate, inclusiv în istoric și răspuns în curs.
- [ ] Workerul cu lease pierdut nu poate modifica artefactele sau starea sursei.
- [ ] Revocarea/retragerea, cotele și idempotency sunt verificate cu cereri concurente reale.
- [ ] Interfața trece E2E la 360/768/1440px, zoom 200%, tastatură și teste de accesibilitate.
- [ ] Providerul real și modelul de embeddings sunt evaluate; simulările refuzate la pornirea mediului public.
- [ ] Restore DB + bytes într-un mediu separat păstrează proprietatea, revocarea și copiile; downloadul este verificat ca destinatar.
- [ ] Runbook-ul selectează explicit stiva Guguță, imaginile sunt reproductibile și scanate, rollback-ul este demonstrat.
- [ ] Readiness primește dovezi reale și GO de la responsabili; simpla încheiere a remedierii nu autorizează deployment.

## 9. Reproducerea verificărilor

Rulați din rădăcina repository-ului, cu `.venv` existent. Serverul indicat trebuie să fie **temporar și dedicat testării**; fixture-urile sunt distructive pentru bazele lor de test și resetează parolele rolurilor pe acel server. Nu folosiți DSN de pilot/producție.

```powershell
$env:GUGUTA_TEST_DATABASE_URL = 'postgresql+psycopg://guguta_migrator:guguta_audit_local@127.0.0.1:55434/guguta'
.venv\Scripts\python.exe -m pytest tests/guguta -q --ignore=tests/guguta/test_a22_restore.py --basetemp=.audit-tmp-suite -p no:cacheprovider --disable-warnings
.venv\Scripts\python.exe -m pytest docs/guguta/audit-2026-09-06/test_probes.py -q --basetemp=.audit-tmp-probes -p no:cacheprovider --disable-warnings
```

Prima comandă a trecut cu 60 teste. A doua a trecut cu 5 probe care confirmă defectele F01/F07/F09/F10/F14. Nu includeți aceste probe ca teste de acceptare „verzi” fără inversarea așteptărilor după remediere. Build-ul frontend se execută separat din `frontend-guguta` cu `npm.cmd run build`.
