# Evaluarea tehnică Open Notebook pentru Guguță

Revizie: 1.0 · 6 septembrie 2026
Bază analizată: Open Notebook 1.14.0, commit `8297bb22e2eaeb0d8feafc0538f0d736453571d4`.
Stare: analiză înainte de implementare; migrarea nu este executată.

## 1. Concluzie și limite

Continuăm cu fork-ul Open Notebook și înlocuim SurrealDB cu PostgreSQL. Decizia este acceptată; nu mai cerem o nouă alegere a bazei sau aprobarea eliminării SurrealDB.

Se reutilizează experiența de carnet, componente frontend, parsarea și adaptoarele AI. Se reconstruiesc persistența, proprietatea, autorizarea și operațiile Guguță. Migrarea este incrementală, cu un flux complet mic verificat înaintea extinderii funcțiilor.

[SPECIFICATII_GUGUTA.md](SPECIFICATII_GUGUTA.md) stabilește comportamentul. [GHID_IMPLEMENTARE_LLM.md](GHID_IMPLEMENTARE_LLM.md) precizează execuția. [ANALIZA_OSS.md](ANALIZA_OSS.md) păstrează justificarea alegerii.

## 2. Ce este dovedit

În evaluarea locală din 5 septembrie 2026 au fost observate UI pe portul 8502, API pe 5055 cu răspuns healthy, workerul și migrațiile până la versiunea 23. Versiunea produsului afișată era 1.14.0, iar OpenAPI folosea separat versiunea 0.1.0 și avea 115 operații.

Acestea sunt observații istorice, nu o afirmație că serviciile rulează permanent. Docker folosea imaginea flotantă `lfnovo/open_notebook:v1-latest`; nu s-a demonstrat că este construită din commitul local. O versiune afișată identică nu dovedește identitatea codului.

Sursa locală este în `Platforma Guguta/open-notebook`. Remote-ul origin verificat indică upstream; configurarea către fork-ul comunicat de inițiator rămâne de făcut. Volumele existente pot conține fișiere și configurări adăugate în timpul evaluării; se inventariază și se salvează înaintea oricărei migrări. Nu sunt considerate date dispensabile.

Nu există încă probe complete pentru calitatea AI, OCR, audio, citări pe manuale, concurență sau izolare. Prezența unui endpoint ori a unei opțiuni UI demonstrează implementarea unui traseu, nu calitatea rezultatului său.

## 3. Inventarul funcțional și tratamentul în Guguță

| Funcție existentă în cod/UI evaluat | Dovezi locale | Tratament |
| --- | --- | --- |
| Notebook: creare, editare, arhivare, ștergere, recent accesate | api/routers/notebooks.py; frontend/src/app/(dashboard)/notebooks | Carnet digital personal, proprietar obligatoriu |
| Surse: fișier, URL, text, asociere sursă existentă | api/routers/sources.py; frontend/src/components/sources | Păstrăm fișiere/text; amânăm URL/media/arhive |
| Biblioteca globală de surse | frontend/src/app/(dashboard)/sources | Dezactivată pentru elevi până la izolare; MVP centrat pe carnet |
| Notițe manuale și răspunsuri salvate | api/routers/notes.py; componente NotesColumn și NoteEditorDialog | Păstrăm, private, fără import implicit |
| Chat pe notebook și sesiuni | api/routers/chat.py; open_notebook/graphs/chat.py | Portare cu autentificare, context și memorie izolate |
| Chat separat pe sursă | api/routers/source_chat.py; open_notebook/graphs/source_chat.py | Amânat în UI; ruta neportată este dezactivată |
| Text search și vector search | api/routers/search.py; open_notebook/domain/notebook.py | Căutare autorizată pe carnet în PostgreSQL |
| Ask pe baza globală | open_notebook/graphs/ask.py | Nu se expune elevilor în forma upstream |
| Citări interactive | frontend/src/components/ui/markdown-renderer.tsx | Validare autorizație și legături la copia destinatarului |
| Transformări și playground | api/routers/transformations.py; frontend/src/app/(dashboard)/transformations | Motor intern/admin; fără playground pentru elev |
| Podcasturi și profiluri | api/routers/podcasts.py, episode_profiles.py, speaker_profiles.py; commands/podcast_commands.py | Amânare; nu cerem funcționare audio pentru MVP |
| Furnizori, chei și modele implicite | api/routers/credentials.py; open_notebook/ai | Păstrăm abstractizarea, administrare centrală |
| Setări extracție, OCR/formule/imagini | frontend/src/app/(dashboard)/settings; runtime_capabilities.py | Administrator; runtime-uri opționale, testate separat |
| Rebuild embeddings și informații versiune | api/routers/embedding_rebuild.py; pagina advanced | Administrator, reindexare versionată |
| Traduceri, temă, navigare rapidă | frontend/src/lib/locales; componente layout | Păstrăm infrastructura și adăugăm ro-MD |

Formatele declarate upstream includ documente, media, imagini și ZIP; existența listei nu certifică extragerea corectă pentru fiecare format. Guguță MVP folosește PDF cu text, DOCX, PPTX, TXT/Markdown și text introdus. OCR pentru scanări se activează ulterior sau într-un flux editorial separat verificat.

Transformările observate: Analyze Paper, Dense Summary, Key Insights, Reflections, Simple Summary și Table of Contents. Aceste prompturi nu echivalează cu module de flashcard-uri ori quiz-uri.

Furnizorii enumerați upstream includ servicii cloud, Ollama și endpointuri compatibile. Compatibilitatea românei, retenția datelor și costul se verifică pentru modelele alese, nu pentru simpla existență a adaptorului.

## 4. Constatări care schimbă planul de migrare

### 4.1 Relațiile surselor nu sunt copii

În [api/routers/notebooks.py](open-notebook/api/routers/notebooks.py), asocierea sursei creează o relație cu același obiect. Aceasta nu implementează copia independentă Guguță.

[open_notebook/domain/notebook.py](open-notebook/open_notebook/domain/notebook.py) distinge la ștergere sursele exclusive de cele legate de alte notebook-uri. Schema Guguță trebuie să separe SourceAsset, MaterialVersion și NotebookSource; ștergerea copiei nu șterge resursa comună.

Unele ghiduri upstream descriu o singură sursă per notebook sau exporturi mai ample decât ce se observă în cod. Pentru implementare se urmează codul versionat și contractul Guguță, nu aceste formulări contradictorii.

### 4.2 Chatul și Ask au fluxuri diferite

[graphs/chat.py](open-notebook/open_notebook/graphs/chat.py) transmite modelului contextul primit și mesajele. [graphs/ask.py](open-notebook/open_notebook/graphs/ask.py) construiește căutări și apelează vector_search fără un proprietar/carnet în argumentele acelei apelări.

Prin urmare, nu presupunem că orice întrebare din notebook face deja RAG pe fragmente sau că există căutare hibridă integrată. Sunt implementate căutări text și vector distincte; combinarea lor, filtrarea autorizată și limitele pentru manuale trebuie proiectate și măsurate.

### 4.3 Memoria este și în SQLite

[graphs/chat.py](open-notebook/open_notebook/graphs/chat.py) și [graphs/source_chat.py](open-notebook/open_notebook/graphs/source_chat.py) folosesc SqliteSaver și LANGGRAPH_CHECKPOINT_FILE. Migrarea exclusivă a tabelelor SurrealDB nu mută și această memorie.

Ghidul propune mesaje durabile în PostgreSQL și reconstrucția explicită a contextului pentru chatul MVP. Dacă se păstrează checkpointuri LangGraph, se folosește persistență PostgreSQL cu verificarea accesului înainte de load/resume, namespace derivat pe server și revizie de context. RLS sau un UUID de sesiune nu sunt singure suficiente dacă saverul ocolește verificarea.

### 4.4 Coada și joburile depind de SurrealDB

Dependența include surreal-commands, modelele, migrațiile, interogările inline, funcțiile text/vector și ID-urile de forma table:id. Nu este o schimbare exclusiv în repository.

Numărul „91 de fișiere cuplate” din revizia anterioară provenea dintr-o căutare prea largă, inclusiv săgeți și texte fără dependență efectivă. Nu îl folosim drept estimare. Inventarul real se construiește după importuri, apeluri, migrații și trasee executate.

### 4.5 Asincronismul trebuie verificat, nu presupus

Codul chatului include apeluri sincrone și adaptări cu event loop/thread. Se revizuiesc blocarea API-ului, anularea, timeouturile și dimensionarea poolurilor. Extracția grea rămâne în worker; cererile LLM nu țin tranzacții SQL deschise.

## 5. Arhitectura țintă de lucru

| Zonă | Alegere de lucru | Ce se finalizează prin ADR |
| --- | --- | --- |
| UI | Next.js/React, TypeScript, componente existente | Organizare rute, tokens și fluxuri mobile |
| API | FastAPI/Pydantic, servicii și repositories | Contracte versionate și eliminarea rutelor neportate |
| DB | PostgreSQL + pgvector | Versiuni fixate, schema, politici de acces, dimensiuni/indexuri |
| Acces DB | SQLAlchemy async, psycopg 3, Alembic | Compatibilitate cu versiunea Python și test de migrare |
| Worker | Joburi durabile PostgreSQL, proces separat | Lease, heartbeat, retry, concurență și compensare |
| Chat | Mesaje PostgreSQL, context reconstruit per revizie | Checkpointer PostgreSQL numai dacă fluxul îl necesită |
| Fișiere | Filesystem privat în development, adaptor object storage | Backendul production și retenția |
| Identitate | OIDC Authorization Code + PKCE prin adaptor, sesiune opacă server-side | Furnizor, login minorilor și recuperarea accesului |
| Infrastructură | Docker Compose pentru development/pilot limitat | Sizing, backup, domeniu/TLS și responsabil operare |

Acestea sunt instrucțiuni tehnice propuse prin ghid, nu funcții deja instalate. Nu introducem microservicii, Kubernetes sau organizații școlare ca obligații MVP.

## 6. Modelul datelor și limitele de acces

Modelul canonic se află în §9 din specificații: User, DigitalNotebook, SourceAsset, MaterialVersion, NotebookSource, ProcessingArtifact/Chunk/Embedding, TemplateVersion, ShareSnapshot, ShareImport, ChatSession/Message/Citation și Note.

Reguli de implementare:

- Accesul la fișier și fragmente pornește de la NotebookSource autorizat, nu de la hash sau asset ID.
- Copiile au relații locale și contexte personale distincte; nu se copiază cheia străină către sursa personală a autorului.
- Manifestele fixate păstrează versiunea materialului și metadatele de atribuire.
- Cache-urile și checkpointurile includ domeniul utilizatorului și revizia de context.
- Reindexarea creează o versiune separată; modelul/dimensiunea vectorilor nu se schimbă în loc.
- Pachetele active, șabloanele publicate și importurile în curs păstrează referințe care împiedică ștergerea prematură a octeților.

## 7. Ce se elimină, ascunde sau amână

**Eliminare din runtime-ul țintă:** serviciul și driverul SurrealDB, surreal-commands, SQL-ul specific upstream, starea SQLite de chat neportată și parola unică a instanței. Codul istoric rămâne recuperabil din Git; volumele se păstrează până la migrare verificată.

**Administrator:** chei, modele, transformări, configurație extracție și reconstruirea indexurilor. Ascunderea UI este însoțită de autorizare în API.

**Amânare cu dezactivare server-side:** Podcasts, profiluri, chat pe sursă, Ask global, URL/media/arhive, OCR avansat. Nu se migrează obligatoriu aceste fluxuri doar pentru a păstra paritate integrală upstream.

**Design:** textul vizibil devine „Carnet digital”. ID-urile, tabelele și endpointurile nu se redenumesc cosmetic în fiecare PR dacă nu este necesar; schimbările de contract se fac explicit și frontendul se adaptează concomitent.

## 8. Migrare fără pierdere de date

1. Inventariere fără afișarea secretelor: Git, versiuni, volume, fișiere, chei necesare decriptării și SQLite.
2. Copii de siguranță și probă de restaurare. Nu se șterg volume și nu se rulează down cu ștergere de volume ca metodă de upgrade.
3. Mediu PostgreSQL separat cu date sintetice; vechiul demo rămâne reper până la decizia de transfer.
4. Portarea unui flux complet cu identitate și autorizare încă de la CRUD.
5. Portarea formatelor MVP, notițelor și administrării necesare.
6. Inventar al datelor vechi care se păstrează și mapare către un proprietar desemnat. Datele single-user nu pot fi atribuite automat tuturor utilizatorilor.
7. Dacă se cere import de date vechi: export controlat, mapare ID-uri/citări, fișiere și mesaje/checkpointuri, raport de reconciliere, dry-run, apoi transfer aprobat.
8. Cutover verificat cu plan de rollback. Nu presupunem că un backup vechi poate fi restaurat fără a pierde scrieri noi; fereastra și tratarea lor se stabilesc în runbook.
9. Eliminarea dependențelor SurrealDB și a configurațiilor vechi numai după verificarea traseelor MVP. Snapshoturile de backup rămân conform retenției.

Un utilitar complet pentru toate funcțiile istorice nu este obligatoriu pentru MVP; păstrarea sigură a datelor existente este obligatorie până la o decizie explicită asupra lor.

## 9. Secvența de implementare

| Livrare | Conținut | Poartă de acceptare |
| --- | --- | --- |
| Fundație | Fork, ADR, Compose separat, CI și schema cu identitate | Build reproductibil, migrații, niciun secret în Git |
| Primul flux | Doi utilizatori, carnet, PDF, worker, căutare și chat/citări | A04/A11/A12/A13/A17; restart și zero acces încrucișat |
| Produs MVP | Formate, notițe, română, admin, design | Fluxuri de elev complete și rute admin refuzate |
| Catalog | Publicare versionată și instanțiere | A02/A03/A05/A14/A18 |
| Distribuire | Snapshot, import, idempotency și revocare | A07–A10/A15/A16/A19/A20/A28 |
| Lansare pilot | Restaurare, securitate, evaluare pedagogică | Checklist deployment complet pentru mediul ales |

Testarea, logurile, autorizarea și infrastructura de dezvoltare sunt transversale. Nu se așteaptă „etapa de testare” pentru a le introduce.

## 10. Licențe

[Open Notebook LICENSE](open-notebook/LICENSE) este MIT. SurrealDB este înlocuit conform deciziei existente; referința versionată de licență este [SurrealDB 2.0 BSL](https://raw.githubusercontent.com/surrealdb/surrealdb/v2.0.0/LICENSE). Nu deducem licența serverului din licența SDK-ului Python.

PostgreSQL/pgvector și fiecare nouă dependență se inventariază în build. Componentele audio/OCR amânate nu se instalează automat dacă nu sunt necesare. Fixarea versiunilor și SBOM-ul sunt dovezi ale release-ului, nu afirmații făcute anticipat în acest document.

## 11. Corecțiile reviziei finale

Au fost închise deciziile deja acceptate, uniformizat „Începe din nou” pe versiunea publicată curentă și aliniate formatele și modelul datelor cu specificațiile. Au fost corectate afirmațiile despre RAG, asincronism și numărul de fișiere afectate. Au fost adăugate memoria SQLite, construirea imaginii din sursă, protejarea volumelor și separarea funcțiilor MVP de paritatea integrală upstream.
