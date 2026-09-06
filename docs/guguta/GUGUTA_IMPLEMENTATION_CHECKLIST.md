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

- [ ] Verificăm HEAD, branch, remotes și modificările locale.
- [ ] Citim AGENTS.md și documentăm diferențele dintre direcția upstream și Guguță.
- [ ] Inventariem volumele, fișierele, persistența SQLite și necesarul de recuperare a secretelor fără a afișa valori.
- [ ] Salvăm datele existente prin backup coerent și verificăm restaurarea.
- [ ] Configurăm origin către fork și upstream către Open Notebook, fără reclonare peste checkout.
- [ ] Fixăm commitul de bază și strategia de actualizări upstream.
- [ ] Creăm ramura de lucru și convențiile de PR/release.
- [ ] Păstrăm LICENSE MIT și adăugăm registrul de proveniență.
- [ ] Versionăm un singur set canonic de documente în fork, cu linkuri actualizate.
- [ ] Scriem ADR-urile PostgreSQL/vectori, joburi, identitate, stocare, memorie și copii independente.
- [ ] Fixăm politica de licențe și inventariem dependențele obligatorii.
- [ ] Pornim CI cu lint, tipuri, teste și scanare de secrete; protecția ramurii se configurează unde există acces.
- [ ] Înregistrăm deciziile externe încă necesare cu responsabil și termen.

**Închidere:** date protejate, inventar și bază reproductibilă. Nu presupunem că fork-ul comunicat are deja configurate remote-urile checkoutului.

## L1 — PostgreSQL și schemă

- [ ] Pornim un Compose separat pentru Guguță, fără a șterge volumele demo.
- [ ] Fixăm PostgreSQL 17 la un patch suportat și pgvector compatibil.
- [ ] Introducem SQLAlchemy async, psycopg 3 și Alembic cu versiuni blocate.
- [ ] Configurăm roluri separate pentru migrator, API și worker.
- [ ] Definim User/Identity/Session și DigitalNotebook cu proprietar obligatoriu.
- [ ] Definim SourceAsset, MaterialVersion și NotebookSource distincte.
- [ ] Definim ProcessingArtifact/Chunk/Embedding cu metadate de versiune și dimensiune.
- [ ] Definim mesajele/citările și notițele cu relații consistente de proprietate.
- [ ] Adăugăm constrângeri, indici și timestampuri UTC.
- [ ] Scriem politicile RLS și testele cu rolul runtime real.
- [ ] Rulăm migrarea de la zero și testăm upgrade-ul între versiuni Guguță.
- [ ] Adăugăm health checks și un migrator unic pe release.
- [ ] Documentăm .env.example fără secrete și pornirea Windows/Linux.

**Închidere:** schema și infrastructura nouă rulează. Nu se cere încă paritate cu toate rutele upstream.

## L2 — Identitate și CRUD autorizat

- [ ] Implementăm adaptorul OIDC și sesiunea opacă server-side.
- [ ] Implementăm ActorContext și stabilirea identității numai pe server.
- [ ] Adăugăm cookie-uri, CSRF, expirare, logout și revocare.
- [ ] Definim rolurile utilizator, editor de catalog și administrator; profesorul poate folosi rolul obișnuit.
- [ ] Izolăm modul de autentificare sintetică pentru teste/development.
- [ ] Refuzăm auth de test la startup staging/production.
- [ ] Portăm creare/listare/editare/arhivare/ștergere carnet.
- [ ] Paginăm listele și validăm sortarea.
- [ ] Testăm ID-uri străine și falsificarea owner_id.
- [ ] Testăm conexiunile refolosite din pool și contextul RLS după rollback.
- [ ] Dezactivăm rutele upstream neportate; nu rămâne ocolire globală în API.
- [ ] Obținem două conturi sintetice cu date independente.

**Închidere:** A04/A11 aplicabile CRUD și A23 trec înainte de încărcarea documentelor.

## L3 — Materiale și worker

- [ ] Implementăm adaptorul de stocare privată și căi generate de server.
- [ ] Validăm MIME, mărime, pagini și fișiere invalide.
- [ ] Introducem scanare/izolare parser și protecția path traversal/decomprimare.
- [ ] Salvăm hash, MaterialVersion și asocierea locală.
- [ ] Păstrăm originalele necesare importului/downloadului; nu activăm auto-delete upstream.
- [ ] Introducem ProcessingJob în PostgreSQL, creat în tranzacția obiectului țintă.
- [ ] Implementăm claim, lease token, heartbeat și recuperare după crash.
- [ ] Implementăm backoff, limite, retry și anulare.
- [ ] Refuzăm publicarea rezultatelor cu lease/revizie expirate.
- [ ] Portăm PDF text: extracție, locatori, segmentare și embedding.
- [ ] Explicăm eroarea PDF scanat fără OCR; nu declarăm succes fals.
- [ ] Separăm starea extracției/indexării de transformările opționale.
- [ ] Testăm workerul cu doi utilizatori și joburi întârziate.
- [ ] Implementăm stările UI de upload/progres/eroare/retry.

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
