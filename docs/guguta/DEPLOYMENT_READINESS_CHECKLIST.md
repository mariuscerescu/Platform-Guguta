# Guguță — Deployment readiness checklist

Versiune: 1.0 · 6 septembrie 2026
Stare inițială: **NEEVALUAT — nicio lansare aprobată prin acest document.**

Acest checklist se completează pentru un release și un mediu concret. Este separat de [checklistul de implementare](open-notebook/GUGUTA_IMPLEMENTATION_CHECKLIST.md). Codul terminat nu echivalează cu disponibilitatea pentru elevi reali.

Surse: [specificații](SPECIFICATII_GUGUTA.md), [ghid LLM](GHID_IMPLEMENTARE_LLM.md), [evaluare tehnică](EVALUARE_OPEN_NOTEBOOK_PENTRU_GUGUTA.md).

## 1. Fișa release-ului

| Câmp | Valoare de completat |
| --- | --- |
| Release / commit Git | NEPRECIZAT |
| Mediu: staging / pilot / production | NEPRECIZAT |
| Imagini și digesturi | NEPRECIZAT |
| Versiune schemă/Alembic și extensie pgvector | NEPRECIZAT |
| Domeniu și origine publică | NEPRECIZAT |
| Model chat / embedding / dimensiune | NEPRECIZAT |
| Versiune prompt și parser/chunker | NEPRECIZAT |
| Corpus/șabloane pilot și versiuni | NEPRECIZAT |
| Responsabil release | NEPRECIZAT |
| Responsabil tehnic de intervenție | NEPRECIZAT |
| Responsabil pedagogic/conținut | NEPRECIZAT |
| Fereastră de lansare și mentenanță | NEPRECIZAT |
| Capacitate/concurență țintă | NEPRECIZAT |
| Praguri latență, cost și disponibilitate | NEPRECIZAT |
| RPO / RTO și retenție | NEPRECIZAT |
| Locația dovezilor și raportului CI | NEPRECIZAT |
| Aprobare go/no-go | NEACORDATĂ |

Un prag necompletat nu este un prag trecut. LLM-ul poate propune valori și executa măsurători, dar nu inventează aprobarea instituțională sau a inițiatorului.

## 2. Reguli de completare

Folosește `[ ]` pentru nevalidat și `[x]` numai când există dovadă. Pentru „nu se aplică” păstrează elementul nebifat și adaugă motivul și responsabilul care l-a acceptat. Nu se admite N/A pentru autentificare, izolarea datelor, contractul copiilor sau backupul unui mediu cu date reale.

Fiecare grup se închide cu: rezultat, link/cale la dovadă, commit, dată și responsabil. Pentru o probă încă blocată se notează cauza. Un test executat pe alt commit nu certifică automat release-ul curent.

| Nivel | Semnificație |
| --- | --- |
| B — blocant | Oprește expunerea mediului respectiv până la remediere și retestare |
| P — pilot | Obligatoriu înainte de elevi/materiale personale reale |
| O — operare | Obligatoriu pentru susținerea mediului lansat |
| U — ulterior | Nu blochează MVP-ul dacă funcția este dezactivată și indisponibilă server-side |

## 3. Proveniență și build — B

- [ ] R01 — Commitul release-ului este în fork-ul Guguță și coincide cu sursa testată.
- [ ] R02 — Imaginile sunt construite din acel commit și identificate prin digest; nu folosesc v1-latest upstream.
- [ ] R03 — Lockfile-urile și versiunile imaginilor de bază sunt fixate; buildul curat este reproductibil.
- [ ] R04 — Licența MIT și notificările necesare sunt în distribuție.
- [ ] R05 — SBOM-ul și analiza licențelor acoperă backend, frontend, worker și runtime-uri incluse.
- [ ] R06 — Runtime-ul țintă funcționează fără SurrealDB/surreal-commands și fără SQLite neizolat de chat.
- [ ] R07 — Configurațiile/demo-urile upstream nu pot reactiva accidental rute globale sau parola comună.
- [ ] R08 — Secretele și datele personale nu sunt în Git, imagine, frontend bundle, fixture-uri ori rapoarte CI.

Dovadă: raport build, digesturi, inventar dependențe, scanare de secrete și verificarea configurației.

## 4. Migrare, integritate și date existente — B

- [ ] R09 — Migrațiile trec de la bază goală și de la versiunea Guguță precedentă.
- [ ] R10 — Migratorul este unic pe release și folosește privilegii separate de runtime.
- [ ] R11 — Rolul runtime și rolul worker nu sunt superuser/BYPASSRLS și politicile sunt testate cu aceste roluri.
- [ ] R12 — Relațiile de proprietate, FK-urile, versiunile și ID-urile de citare sunt consistente.
- [ ] R13 — Dacă se transferă date vechi, există inventar, proprietar desemnat, dry-run și reconciliere pe număr/hash/referințe.
- [ ] R14 — Volumele și datele vechi sunt păstrate până la validare și decizie explicită.
- [ ] R15 — Migrarea checkpointurilor/mesajelor este demonstrată sau excluderea lor din transfer este aprobată; nu sunt pierdute în tăcere.
- [ ] R16 — Reindexarea cu alt model nu amestecă spații vectoriale incompatibile.
- [ ] R17 — Planul de rollback explică schema și tratarea scrierilor noi; nu se bazează pe downgrade destructiv automat.

Dovadă: rapoarte de migrare, mapare date, rezultate SQL sigure și runbook de revenire.

## 5. Autentificare și autorizare — B

- [ ] R18 — OIDC real este configurat; issuer/audience/PKCE/state/nonce și expirarea sunt validate.
- [ ] R19 — Loginul de test și utilizatorii seed privilegiați sunt imposibili în mediul public.
- [ ] R20 — Cookie-urile, CSRF, logoutul, expirarea și revocarea sesiunilor au teste.
- [ ] R21 — Contul blocat și rolul retras nu păstrează acces prin sesiuni/caches vechi.
- [ ] R22 — A/B sunt izolați în liste, ID direct, download, căutare, citări, streaming, export, joburi și checkpointuri.
- [ ] R23 — Reutilizarea conexiunilor din pool nu păstrează actorul anterior.
- [ ] R24 — Editorul de catalog și autorul unui pachet nu văd conversațiile destinatarilor.
- [ ] R25 — Rutele administrative au verificare pe server; ascunderea meniului nu este singura protecție.
- [ ] R26 — Endpointurile upstream neportate sunt eliminate sau dezactivate pe server.
- [ ] R27 — Accesul prin hash/asset ID nu divulgă sau descarcă fișiere ale altor utilizatori.

Dovadă: matrice de permisiuni, raport integration/E2E și cazuri negative A04/A11/A23.

## 6. Carnete, catalog și distribuire — B

- [ ] R28 — Carnetul gol și cel din șablon au activitate personală goală.
- [ ] R29 — Refresh/dublu click/retry nu creează copii neintenționate.
- [ ] R30 — „Începe din nou” folosește ediția publicată curentă afișată și păstrează carnetul vechi.
- [ ] R31 — Două copii se modifică independent, inclusiv la înlocuirea și ștergerea materialelor.
- [ ] R32 — Snapshotul este fix și folosește numai câmpurile permise.
- [ ] R33 — Importul nu conține chat, notițe, memorie, rezultate personale sau secrete.
- [ ] R34 — Linkul și codul trimit la același pachet și sunt revocate împreună.
- [ ] R35 — Importul revalidează starea și cota în tranzacția finală; concurența cu revocarea este testată.
- [ ] R36 — Retry-ul după timeout recuperează importul deja finalizat; o importare intenționată nouă este permisă.
- [ ] R37 — Importul eșuat nu produce succes fals sau copii parțiale ascunse.
- [ ] R38 — Revocarea și ștergerea contului autorului nu șterg copiile destinatarilor.
- [ ] R39 — GC nu șterge octeți referiți de alte carnete, șabloane, snapshoturi sau importuri/joburi în curs.
- [ ] R40 — Cotele sunt logice și verificarea concurentă nu poate fi ocolită prin deduplicare.

Dovadă: teste A02/A03/A05/A07–A10/A14–A21/A28, inclusiv teste tranzacționale simultane.

## 7. Documente, AI și worker — B

- [ ] R41 — Formatele MVP sunt validate cu fișiere sintetice și materiale autorizate.
- [ ] R42 — PDF scanat fără OCR/text util nu este prezentat drept sursă gata.
- [ ] R43 — MIME, mărime, pagini, path traversal și decomprimare excesivă au teste.
- [ ] R44 — Fișierele sunt private, preview-ul este sanitizat și downloadul autorizat.
- [ ] R45 — URL/media/arhive și funcțiile amânate sunt dezactivate în API.
- [ ] R46 — Jobul supraviețuiește restartului și expirării lease-ului fără efecte locale duplicate.
- [ ] R47 — Workerul întârziat nu poate publica rezultate pentru revizii vechi sau ținte șterse.
- [ ] R48 — Heartbeat, backoff, timeout, concurență și retry manual sunt verificate.
- [ ] R49 — Căutarea filtrează materialele autorizate înainte de folosirea fragmentelor în model.
- [ ] R50 — Contextul manualelor lungi este bugetat și evaluat; nu se pierde în tăcere finalul manualului.
- [ ] R51 — Sursele eliminate/schimbate nu reapar prin mesaje vechi, rezumate, checkpointuri sau stream în curs.
- [ ] R52 — Citările sunt autorizate și reale; pagini/slide-uri nu sunt inventate.
- [ ] R53 — Furnizor indisponibil, rate limit și timeout au comportament controlat și mesaj util.
- [ ] R54 — Costurile și încercările AI sunt măsurate; limitele sunt aplicate pe server.
- [ ] R55 — Cheile AI nu apar în UI/loguri și rotația este verificată.
- [ ] R56 — Prompt injection nu acordă acces sau instrumente suplimentare.

Dovadă: integration tests, probe live separate de mock, rapoarte de procesare și scenarii de avarie.

## 8. UI, design și accesibilitate — B pentru fluxurile esențiale

- [ ] R57 — Interfața folosește „Carnet digital” și română cu diacritice.
- [ ] R58 — Pagina principală distinge catalogul oficial de carnetele personale.
- [ ] R59 — Layoutul funcționează la 360, 768 și 1440px și zoom 200%.
- [ ] R60 — Navigarea cu tastatura, focusul dialogurilor, contrastul și etichetele sunt verificate.
- [ ] R61 — Loading/empty/error/retry/disabled/success sunt implementate pentru toate fluxurile MVP.
- [ ] R62 — Importul/share-ul prezintă clar lista și excluderea conversațiilor/notițelor.
- [ ] R63 — Revocarea și ștergerea explică efectul real.
- [ ] R64 — Streamingul poate fi oprit și nu corupe istoricul la reconnect/retry.
- [ ] R65 — UI nu expune termeni de infrastructură sau configurarea modelelor elevului.
- [ ] R66 — Nu există butoane aparent active conectate doar la mock-uri în buildul livrat.

Dovadă: E2E CLI, capturi din teste, verificare de accesibilitate și revizie umană a fluxurilor.

## 9. Rețea, containere și configurație — B

- [ ] R67 — Domeniul/TLS sunt valide, iar certificatul are reînnoire monitorizată.
- [ ] R68 — UI/API au originea configurată corect; CORS și trusted proxy sunt restrânse.
- [ ] R69 — DB, workerul, fișierele și porturile de debug nu sunt expuse public.
- [ ] R70 — Rulează imagini de producție, fără hot reload, fără socket Docker montat.
- [ ] R71 — Privilegiile, volumele și limitele CPU/RAM/temporare sunt explicite.
- [ ] R72 — Liveness/readiness/worker heartbeat disting proces blocat, schemă invalidă și furnizor AI indisponibil.
- [ ] R73 — Startup-ul refuză secrete default, auth test și configurații nesigure.
- [ ] R74 — Scanările nu au vulnerabilități critice exploatabile nerezolvate; celelalte constatări au tratament documentat.
- [ ] R75 — CSP, sanitizarea, Referrer-Policy și protejarea linkurilor cu token sunt verificate.
- [ ] R76 — Rate limiting funcționează coerent pentru numărul real de instanțe.

Dovadă: configurație redactată, scanări, teste rețea și verificări HTTP.

## 10. Backup, recuperare și monitorizare — O, obligatoriu cu date reale

- [ ] R77 — Backup automat pentru DB, fișiere și configurația recuperabilă este activ.
- [ ] R78 — Secretele necesare decriptării au procedură separată de recuperare.
- [ ] R79 — Un backup real este restaurat într-un mediu separat.
- [ ] R80 — După restore sunt verificate conturi, citări, fișiere, snapshoturi revocate și independența copiilor.
- [ ] R81 — Duratele măsurate și pierderea posibilă de date respectă RTO/RPO convenite.
- [ ] R82 — Joburile expirate nu sunt executate necontrolat după restaurare.
- [ ] R83 — Există alerte pentru API, worker, coadă veche, spațiu, cost și backup eșuat.
- [ ] R84 — Logurile au request/job ID, retenție și acces limitat; fără PII/secrete implicite.
- [ ] R85 — Un responsabil real primește și verifică alertele.
- [ ] R86 — Runbookul deploy/rollback a fost probat în staging.

Dovadă: raport restore cu durate, reconciliere, alertă de test și runbook.

## 11. Acceptarea pilotului cu elevi — P

- [ ] R87 — Clasele/disciplinele, participanții și condițiile pilotului sunt stabilite.
- [ ] R88 — Drepturile de utilizare/redistribuire ale materialelor sunt înregistrate.
- [ ] R89 — Profesorul desemnat a verificat extracția, întrebările și răspunsurile.
- [ ] R90 — Evaluarea românei/citărilor are praguri stabilite înainte de test și le îndeplinește.
- [ ] R91 — Furnizorii AI, destinațiile datelor și condițiile de retenție sunt aprobate pentru pilot.
- [ ] R92 — Accesul minorilor, informarea, retenția, exportul și ștergerea datelor sunt clarificate instituțional.
- [ ] R93 — Există raportare conținut/răspuns problematic și responsabil de intervenție.
- [ ] R94 — Testul de încărcare folosește ținta reală și respectă pragurile de cost/latency convenite.
- [ ] R95 — Există limite de cost și mecanism de oprire a funcțiilor AI fără pierdere de date.
- [ ] R96 — Nu există probleme de izolare sau securitate blocante deschise.

Dovadă: raport pedagogic, inventar materiale, decizii instituționale, benchmark și buget. Un LLM nu semnează în locul responsabililor.

## 12. Go / no-go și lansare

### Înainte de comutare

- [ ] R97 — Toate controalele B și controalele O/P aplicabile au dovezi pentru release.
- [ ] R98 — Responsabilul release-ului a consemnat explicit GO pentru mediul și fereastra date.
- [ ] R99 — Backupul pre-release este valid și imaginea anterioară este disponibilă.
- [ ] R100 — Migrările și incompatibilitățile sunt cunoscute; scrierile sunt controlate dacă migrarea o cere.
- [ ] R101 — Există autorizare pentru deployment, distinctă de redactarea ghidului și checklistului.

**NO-GO:** orice acces încrucișat, auth de test public, date/backup nerecuperabile, import cu date private, licență obligatorie neacceptată, migrare netestată sau lipsa deciziilor de pilot pentru elevi reali.

### După deployment

- [ ] R102 — Health/readiness și versiunea expusă corespund release-ului.
- [ ] R103 — Două conturi sintetice autorizate trec smoke testul: carnet, PDF, căutare, chat/citare, izolare.
- [ ] R104 — Share/import/revocare și independența copiilor sunt verificate cu date sintetice.
- [ ] R105 — Workerul procesează joburi, iar erorile și costurile sunt în limite.
- [ ] R106 — Conectarea administratorului și refuzul accesului elevului la admin sunt verificate.
- [ ] R107 — Monitorizarea și backupul programat funcționează.
- [ ] R108 — Perioada de observație convenită este încheiată și decizia de menținere/rollback este înregistrată.

Smoke testul nu folosește documente ale elevilor și nu șterge obiecte străine de fixture-urile create pentru el.

## 13. Raport final de readiness

| Câmp | Rezultat |
| --- | --- |
| Controale validate / nevalidate | DE COMPLETAT |
| Controale N/A și justificări | DE COMPLETAT |
| Probleme blocante | DE COMPLETAT |
| Riscuri acceptate, responsabil și termen | DE COMPLETAT |
| Teste CI/integration/E2E și commit | DE COMPLETAT |
| Raport restaurare | DE COMPLETAT |
| Evaluare pedagogică și performanță | DE COMPLETAT |
| Decizie | NO-GO până la evaluare |
| Aprobat de / data | NEACORDAT |
| Observații post-release | DE COMPLETAT |

Funcțiile U — Flashcards, Quiz și Prezentare audio — nu blochează MVP-ul dacă sunt indisponibile pe server și nu sunt promovate drept funcționale. Introducerea lor cere propria evaluare de licență, cost, securitate și calitate.
