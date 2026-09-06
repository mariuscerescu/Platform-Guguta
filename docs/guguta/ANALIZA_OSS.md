# Guguță — Alegerea bazei open-source

Revizie: 1.0 · 6 septembrie 2026
Stare: alegerea bazei este închisă; validarea migrării și a pilotului rămâne deschisă.

## 1. Decizia actuală

**Platforma Guguță se dezvoltă prin refactorizarea fork-ului Open Notebook [mariuscerescu/Guguta-Platform](https://github.com/mariuscerescu/Guguta-Platform).** Inițiatorul a acceptat păstrarea Next.js/FastAPI și înlocuirea SurrealDB cu PostgreSQL și stocare vectorială, împreună cu introducerea utilizatorilor și a autorizării.

Recomandarea anterioară AnythingLLM este înlocuită. Nu mai există o etapă obligatorie de comparație AnythingLLM înaintea dezvoltării Guguță. Alternativele rămân referințe istorice, utile numai dacă apar dovezi că migrarea aleasă nu este viabilă.

Documentele au responsabilități distincte:

- [SPECIFICATII_GUGUTA.md](SPECIFICATII_GUGUTA.md): cerințe și comportament; sursa principală pentru produs.
- [EVALUARE_OPEN_NOTEBOOK_PENTRU_GUGUTA.md](EVALUARE_OPEN_NOTEBOOK_PENTRU_GUGUTA.md): componente existente, limite și migrare.
- [GHID_IMPLEMENTARE_LLM.md](GHID_IMPLEMENTARE_LLM.md): instrucțiuni concrete de execuție.
- [Checklist de implementare](open-notebook/GUGUTA_IMPLEMENTATION_CHECKLIST.md): progres.
- [DEPLOYMENT_READINESS_CHECKLIST.md](DEPLOYMENT_READINESS_CHECKLIST.md): dovezi necesare lansării.

## 2. Motivul alegerii

Open Notebook oferă o experiență apropiată de Carnet digital: surse, notițe, conversații, controlul contextului și citări. Reutilizarea interfeței, parsării documentelor și integrărilor AI reduce codul care trebuie construit de la zero.

Refactorizarea are un cost real: modelul single-user, persistența, căutarea, checkpointurile conversațiilor și workerul trebuie adaptate. Portarea nu se reduce la schimbarea unui driver; funcțiile AI nu sunt deja validate pentru manualele din Moldova.

| Abordare | Avantaj | Cost/risc | Decizie |
| --- | --- | --- | --- |
| Refactorizare Open Notebook | Experiență de carnet și componente AI existente | Migrare DB/coadă/memorie, identitate și autorizare | Aleasă |
| Produs complet de la zero | Libertate totală a schemei și UI | Reconstrucție ingestie, chat, citări, UI, integrări și operare | Nu este abordarea curentă |
| Motor AnythingLLM în spatele aplicației Guguță | Motor documentar și multi-user documentat | Contract de permisiuni și produs propriu în față | Alternativă istorică, neimplementată |

Nu atribuim procente de reutilizare, durate sau costuri fără măsurarea primei probe funcționale.

## 3. Dovezi și limite

Sursa locală Open Notebook a fost verificată la commitul `8297bb22e2eaeb0d8feafc0538f0d736453571d4`, versiune de produs 1.14.0. În evaluarea din 5 septembrie au fost observate interfața Docker, API-ul, migrațiile și workerul.

Docker Compose folosea imaginea `lfnovo/open_notebook:v1-latest`, nu un build demonstrat al checkoutului local. Aceeași versiune afișată nu dovedește identitatea exactă a codului imaginii cu acel commit. Buildul Guguță trebuie produs și etichetat dintr-un commit fix.

Revizia finală verifică documentele și codul local; nu reprezintă retestarea live a tuturor funcțiilor, benchmark, audit exhaustiv sau probă de scalabilitate. Nu au fost măsurate calitatea românei, recuperarea informației, fidelitatea citărilor sau costul pe elev.

Fork-ul este cel comunicat de inițiator. La verificarea locală, `origin` indica încă `lfnovo/open-notebook`; configurarea remote-urilor fork/upstream rămâne sarcină de implementare.

## 4. Comparația istorică

Tabelul rezumă evaluarea anterioară. Alternativele nu au fost reinstalate sau reevaluate integral în această revizie; licențele și funcțiile lor se reverifică la un commit fix dacă se decide reutilizarea codului.

| Proiect | Observație din evaluarea anterioară | Poziție în decizia curentă |
| --- | --- | --- |
| [Open Notebook](https://github.com/lfnovo/open-notebook) | Aplicație MIT, carnet/surse/chat, API, podcasturi; single-user și SurrealDB | Baza aleasă, cu refactorizarea fundației |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | MIT, workspaces și multi-user; rolurile necesită verificare pentru crearea spațiilor de către elev | Alternativă istorică |
| [SurfSense](https://github.com/MODSetter/SurfSense) | Nucleu Apache 2.0 și componente BSL în evaluarea inițială | Nu corespunde cerinței de proiect de bază MIT |
| [ThinkFlow / Open-NotebookLM](https://github.com/OpenDCAI/ThinkFlow) | Apache 2.0; instrumente de studiu documentate, izolare nevalidată local | Referință funcțională |
| [Kotaemon](https://github.com/Cinnamon/kotaemon) | Apache 2.0; chat documentar, experiență diferită de carnet | Nu este baza MIT aleasă |
| [LearnHouse](https://github.com/learnhouse/learnhouse) | AGPL-3.0 în evaluarea inițială; produs centrat pe cursuri | Model de produs și licență diferite |

Excluderea Apache 2.0 ca licență principală a bazei reflectă cerința inițiatorului; nu înseamnă că o bibliotecă Apache nu poate fi utilizată într-un produs MIT cu notificările aferente. Conturile existente nu dovedesc izolarea; colaborarea nu este importul unei copii independente.

## 5. Licențe și dependențe

Codul Open Notebook este MIT: [LICENSE local](open-notebook/LICENSE). Se păstrează copyrightul și textul licenței în copiile sau porțiunile substanțiale. NOTICE propus pentru Guguță este un registru voluntar de proveniență, nu o obligație suplimentară a MIT.

[Licența SurrealDB 2.0](https://raw.githubusercontent.com/surrealdb/surrealdb/v2.0.0/LICENSE) este BSL 1.1 și se declară ne-open-source. Este o referință versionată din familia v2; tagul Docker flotant `v2` nu identifică patchul exact al instanței evaluate. Decizia Guguță este eliminarea acestei dependențe, fără a mai cere confirmarea aceleiași alegeri.

[PostgreSQL](https://www.postgresql.org/about/licence/) și [pgvector](https://github.com/pgvector/pgvector/blob/master/LICENSE) folosesc licențe permisive PostgreSQL, distincte de MIT. pgvector este alegerea tehnică de lucru pentru vectori, de fixat la o versiune compatibilă prin ADR și build.

Politica de implementare: cod Guguță MIT; dependențe obligatorii OSS compatibile, preferabil permisive; fără componente BSL/source-available în stiva țintă. Fiecare bibliotecă, runtime OCR/audio, imagine Docker și model se inventariază separat. Înlocuirea SurrealDB nu certifică automat toate dependențele.

Ghidul pornește cu joburi persistente în PostgreSQL și filesystem privat pentru dezvoltare, păstrând un adaptor pentru stocare de obiecte. Un nou server de coadă sau stocare nu se introduce cu licență neanalizată.

Licența aplicației nu acordă drepturi asupra manualelor, mărcilor sau vocilor. Drepturile materialelor și condițiile furnizorilor AI se verifică înainte de utilizare.

## 6. Reutilizare și construcție

| Componentă | Tratament |
| --- | --- |
| Next.js, componente surse/chat/notițe, i18n | Păstrare și adaptare la română/elevi |
| Parsare și adaptoare AI | Reutilizare cu probe pe materialele MVP și inventar de licențe |
| Chat și citări | Adaptare pentru recuperare autorizată, buget și proveniență |
| SurrealDB, interogări și migrații | Înlocuire PostgreSQL |
| surreal-commands | Înlocuire worker/joburi PostgreSQL |
| SQLite/checkpointuri de chat | Mutare sau reconstrucție controlată; fără memorie globală neizolată |
| Identitate și autorizare | Construcție pentru utilizatori independenți |
| Catalog, versiuni, instanțiere și snapshoturi | Module Guguță |
| Configurare globală | Zonă administrator, autorizată și în API |
| Audio/quiz/flashcard-uri | Ulterior, fără blocarea probei MVP |

## 7. Prima probă și criteriile de continuare

Prima livrare este un flux complet cu **doi utilizatori**, pe PostgreSQL: creare carnet, upload PDF, job, fragmente/vectori, căutare, chat/citări și restart.

Dovezi obligatorii:

- acces încrucișat refuzat în API, fișiere, căutare, streaming, worker și memorie;
- ID-uri și relații consistente, cu migrații aplicabile de la zero;
- surse eliminate care nu reapar din istoricul AI;
- procesare reluabilă și limite explicite de context;
- imagine construită din commit fix, fără SurrealDB;
- probe pe date sintetice și materiale autorizate.

Testele de concurență pentru snapshoturi și pilotul pedagogic urmează acestei probe. Nu este necesară portarea tuturor ecranelor upstream, a podcasturilor sau a bibliotecii globale Ask.

Dacă proba eșuează, se documentează cauza și se reproiectează modulul afectat. Trecerea la alt proiect sau rescrierea integrală cere o decizie nouă a inițiatorului.

## 8. Istoricul reviziei 1.0

Au fost retrase recomandările contradictorii AnythingLLM, înregistrate aprobările existente și separate codul local, demo-ul Docker și comparația istorică. Au fost incluse memoria SQLite, politica de licențe pe componente și proba cu utilizatori izolați.
