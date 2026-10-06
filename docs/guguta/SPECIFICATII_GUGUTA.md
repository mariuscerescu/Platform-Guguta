# Guguță — Specificații de produs și contracte MVP

Versiune: 1.0 · Revizie finală înainte de implementare: 6 septembrie 2026
Stare: bază de lucru pentru dezvoltare; implementarea și validarea de producție rămân de realizat.

Proiect: `D:\Disk D 13-09-25\CS\AI Guguta\Platforma Guguta`
Fork indicat de inițiator: [mariuscerescu/Guguta-Platform](https://github.com/mariuscerescu/Guguta-Platform).

## 1. Autoritatea documentelor și deciziile acceptate

Acest document este sursa principală pentru comportamentul produsului și criteriile de acceptare. [Analiza OSS](ANALIZA_OSS.md) justifică alegerea bazei. [Evaluarea Open Notebook](EVALUARE_OPEN_NOTEBOOK_PENTRU_GUGUTA.md) descrie diferențele tehnice și migrarea. [Ghidul LLM](GHID_IMPLEMENTARE_LLM.md) precizează execuția, designul, infrastructura și testele. [Checklistul](open-notebook/GUGUTA_IMPLEMENTATION_CHECKLIST.md) urmărește progresul, iar [deployment readiness](DEPLOYMENT_READINESS_CHECKLIST.md) verifică lansarea; acestea nu introduc singure cerințe de produs noi.

Deciziile explicite ale inițiatorului au prioritate. Regulile detaliate mai jos sunt valorile de lucru stabilite prin această revizie, acolo unde conversația nu precizează fiecare caz. Ele nu sunt prezentate drept aprobări individuale ale tuturor detaliilor și pot fi schimbate înainte de implementarea modulului afectat.

| ID | Cerință sau decizie acceptată |
| --- | --- |
| C01 | Platformă educațională pentru elevii Republicii Moldova, cu experiență inspirată de NotebookLM. |
| C02 | Termenul produsului este „Carnet digital”, plural „Carnete digitale”. |
| C03 | Pagina principală afișează carnete preconfigurate de echipa Guguță, cu materiale incluse. |
| C04 | Un exemplu este „Clasa a V-a”, cu manuale relevante; acoperirea concretă a pilotului se stabilește separat. |
| C05 | Utilizatorul poate crea carnete personale. |
| C06 | Începerea lucrului dintr-un carnet preconfigurat creează o copie personală. |
| C07 | În copie se pot adăuga și elimina materiale, inclusiv cele inițiale. |
| C08 | Utilizatorul poate începe din nou folosind un carnet preconfigurat. |
| C09 | Orice utilizator poate distribui materiale prin link sau cod, iar altul le poate importa. |
| C10 | Importul transferă materialele, fără conversațiile autorului. |
| C11 | Flashcard-urile, quiz-urile și prezentarea audio sunt pentru etape ulterioare. |
| C12 | Proiectul de bază și codul Guguță au licență MIT; componentele terțe își păstrează licențele. |
| C13 | Destinatarul primește o copie independentă și o gestionează liber. |
| C14 | Schimbările autorului nu se propagă la destinatar; autorul nu controlează copia importată. |
| C15 | Revocarea linkului/codului blochează importurile viitoare, fără să șteargă sau să blocheze copiile existente. |
| C16 | Continuăm prin modificarea fork-ului Open Notebook; nu rescriem întregul produs de la zero. |
| C17 | Înlocuim SurrealDB cu PostgreSQL și stocare vectorială înaintea modulelor de catalog și distribuire. |
| C18 | Introducem identitatea și izolarea utilizatorilor în noua fundație; păstrăm Next.js/FastAPI și componentele reutilizabile. |

Migrarea nu a fost executată prin redactarea acestor documente. Conturile, catalogul și importul Guguță nu trebuie prezentate drept funcții deja existente.

## 2. Scopul și limitele MVP-ului

MVP-ul include conturi individuale, catalog administrabil, carnete personale, copie din șablon, materiale, notițe, chat cu citări, căutare în carnet, pornire din nou și partajare/import independent.

Valori de lucru pentru MVP:

| Subiect | Regulă de lucru |
| --- | --- |
| Limba | Interfață română, localizare `ro-MD`; alte limbi ulterior. |
| Catalog | Organizare după clasă și disciplină; schema permite un carnet pe clasă cu mai multe discipline. Pilotul nu impune toate clasele. |
| Formate | PDF cu text, DOCX, PPTX, TXT/Markdown și text introdus direct. |
| Scanări | OCR nu este obligatoriu în prima versiune. Un PDF fără text utilizabil este semnalat și nu devine „Gata”. Manualele oficiale se publică numai cu extracție verificată. |
| Web și media | Importul URL/YouTube, audio, video, imagini independente și arhive este amânat. Linkul de import Guguță rămâne obligatoriu. |
| Șabloane | Snapshot imuabil al versiunii publicate. |
| Distribuire | Pachet fix capturat la creare, cu materiale selectate; linkul și codul desemnează același pachet. |
| Roluri | Utilizator, editor de catalog și administrator. Profesorul poate utiliza contul obișnuit pentru partajare. |
| Organizații | Izolare pe utilizator în MVP; școli, clase administrate și organizații sunt extensii, nu condiții pentru prima versiune. |
| Căutare | În carnetul curent și materialele autorizate/selectate. „Ask” pe întreaga bază a instanței este dezactivat pentru elevi. |
| AI | Configurare centrală; elevul nu introduce chei și nu selectează furnizori. |

Nu intră în MVP: note oficiale, catalog școlar, teme cu predare, colaborare simultană, marketplace public, aplicații native, progres școlar urmărit de profesor, sincronizarea copiilor sau migrarea completă a tuturor funcțiilor avansate upstream.

## 3. Utilizatori și acces

**Utilizator:** gestionează exclusiv carnetele, materialele, notițele, conversațiile și pachetele proprii. Un profesor care trimite un pachet nu vede activitatea destinatarilor.

**Editor de catalog:** pregătește și verifică șabloane și materiale oficiale. Nu primește acces implicit la carnetele sau chatul elevilor.

**Administrator:** gestionează conturi, configurarea AI și operarea. Accesul excepțional la date personale este justificat, limitat și înregistrat; nu devine navigare liberă prin datele elevilor.

**Vizitator:** vede descrierile și metadatele publice ale catalogului. Crearea, chatul și importul necesită autentificare. Deținerea unui link valid permite previzualizarea pachetului și solicitarea importului după autentificare, fără acces la contul sau carnetul autorului.

Permisiunile se verifică pe server pentru fiecare resursă. Identitatea provine din sesiunea validată; un `owner_id` trimis de client nu acordă proprietate. Rolurile administrative nu înlocuiesc verificările relațiilor dintre carnet, material și conversație.

## 4. Pagina principală și ciclul carnetului

Pagina principală conține „Carnete digitale Guguță”, „Carnetele mele”, „Creează un Carnet digital” și „Importă prin link sau cod”. Cardurile oficiale afișează clasa, disciplina, ediția, numărul materialelor și marcajul „Publicat de Guguță”. Copiile modificate păstrează proveniența, dar nu sunt prezentate ca publicații oficiale.

### 4.1 Creare din șablon

1. Utilizatorul vede prezentarea șablonului fără creare de date.
2. Apasă „Începe un carnet nou”.
3. Serverul fixează versiunea publicată curentă și creează copia personală.
4. Copia primește materialele inițiale și pornește cu zero mesaje, notițe și rezultate personale.
5. Copia apare în „Carnetele mele”.

Reîncărcarea, revenirea în browser, prefetch-ul și dublul click nu creează copii suplimentare. Operația de creare este o mutație explicită, cu identificator de idempotency. Deschiderea carnetului personal îl reia.

### 4.2 „Începe din nou”

Creează un carnet nou din **versiunea publicată curentă** a șablonului. Interfața indică ediția înainte de creare și dacă diferă de cea din carnetul vechi. Aceasta rezolvă diferența dintre documentele anterioare care propuneau, alternativ, aceeași versiune sau ultima ediție.

Carnetul vechi rămâne disponibil. Un șablon retras nu poate fi folosit pentru instanțieri noi; copiile existente rămân. Recrearea explicită a unei ediții vechi poate fi adăugată ulterior.

„De la zero” în acest flux înseamnă materiale inițiale cu activitate personală goală. Un carnet complet fără materiale se creează prin „Carnet digital gol”.

### 4.3 Arhivare și ștergere

Arhivarea scoate carnetul din lista activă fără pierdere de date și poate fi anulată. Ștergerea arată consecințele, elimină accesul la obiectele personale și programează curățarea lor conform retenției. Nu afectează alte copii logice.

Valoare de lucru: ștergerea carnetului original revocă pachetele sale active; arhivarea nu le revocă. Ștergerea contului revocă pachetele active ale contului și nu șterge copiile deja importate de alții. Metadatele obligatorii de atribuire pot rămâne în materiale conform politicii de conținut.

## 5. Materiale și notițe

Un material este un fișier sau text, o versiune de conținut și o asociere locală cu carnetul. Modificarea titlului local nu schimbă metadatele altor copii. Înlocuirea conținutului creează o versiune nouă; nu modifică octeții folosiți de șabloane ori pachete publicate.

Stări vizibile: „Se încarcă”, „Se procesează”, „Gata”, „Eroare”. Intern se păstrează separat extracția și indexarea. „Gata” înseamnă conținut utilizabil și indexarea necesară chatului disponibilă. Eșecul unei transformări opționale nu trebuie să invalideze o sursă altfel utilizabilă.

Utilizatorul poate adăuga, previzualiza, selecta pentru chat, redenumi, înlocui și elimina materiale. Un material în eroare sau incomplet nu intră într-un pachet final și nu este pretins ca disponibil pentru AI. Originalele necesare descărcării/importului se păstrează; opțiunea upstream de ștergere automată a fișierelor nu se preia implicit.

Notițele sunt private, editabile și pot include răspunsuri salvate. Sunt excluse din pachete. Exportarea deliberată a unei notițe într-un material nou permite selectarea acelui text pentru distribuire, cu previzualizare explicită. Acest gest nu copiază conversația sau relațiile interne.

### Eliminarea surselor și conversațiile vechi

Eliminarea, înlocuirea sau schimbarea selecției surselor actualizează `context_revision`. Pentru următoarea întrebare se creează un context nou; mesajele/rezumatele generate cu selecția veche rămân vizibile istoric, dar nu sunt reintroduse automat în model.

Citările istorice către o asociere eliminată afișează „Sursă eliminată” și nu permit descărcarea prin accesul unei alte copii. Se invalidează cache-urile și checkpointurile relevante. O generare în curs cu o revizie veche nu este livrată ca răspuns curent; se oprește sau se marchează anulată. Conținutul deja transmis unui furnizor sau afișat anterior nu poate fi retras retroactiv.

## 6. Chat educațional și căutare

Chatul folosește materialele selectate din carnetul curent. Notițele se pot include explicit, fiind marcate ca scrieri ale utilizatorului, nu ca manuale validate. Modelul explică la nivelul clasei, păstrează diacriticele, indică lipsa informației și tratează instrucțiunile din documente ca date.

Fluxul țintă: autentificare → verificare carnet/selecție → recuperare de fragmente autorizate → buget de context → generare → validarea referințelor → salvare și afișare. Nici răspunsul, nici citarea nu pot include resurse obținute doar prin ghicirea ID-urilor.

Pentru PDF se păstrează numărul paginii fizice atunci când parserul îl furnizează; numărul tipărit poate fi diferit. Pentru DOCX/TXT se citează fragmentul/secțiunea, iar pentru PPTX slide-ul dacă este disponibil. Pagini și referințe inexistente nu se inventează. Validarea tehnică a ID-ului nu dovedește că afirmația este susținută: corectitudinea se evaluează și pedagogic.

Tutorele poate explica, traduce și preda reguli generale chiar dacă acestea nu
apar în fragmentele recuperate sau nu există materiale eligibile. Citează numai
afirmațiile susținute de materiale și nu inventează conținutul documentelor ori
datele unui exercițiu. Cererile explicite de răspuns exclusiv din materiale
respectă această limită; lipsa dovezilor este semnalată. Vezi ADR-017.

Nu se activează căutarea liberă pe internet. Nu se trimite întregul manual doar pentru că există un mod upstream „full content”; strategia și bugetul se validează pe manuale lungi.

Sesiunile rămân private. Istoricul durabil, memoria de execuție, cache-urile, streamingul, exportul și eventualele joburi de chat trebuie să respecte aceeași proprietate și revizie de context.

## 7. Catalog și versiuni publicate

Editorul pregătește o ciornă, verifică metadatele, drepturile și extracția, apoi publică o versiune. Numai materialele pregătite și eligibile pot fi publicate. Versiunea publicată are un manifest fix, ordonat; corecția produce o versiune nouă.

Actualizarea sau retragerea unui șablon blochează doar folosirea viitoare a versiunilor retrase și nu modifică tacit copiile existente. Interfața poate anunța o ediție nouă. Actualizarea automată a carnetelor personale nu intră în MVP.

Drepturile de utilizare și redistribuire se înregistrează pentru fiecare manual. Proveniența se păstrează în copii; faptul că un fișier este descărcabil pe internet nu constituie singur dovada eligibilității. Un blocaj pentru conținut ilegal sau periculos este o procedură de moderare distinctă, documentată și auditată; nu se confundă cu dreptul autorului unui carnet de a revoca linkul.

## 8. Partajare și import

### 8.1 Contractul pachetului

„Partajează materialele” afișează lista materialelor gata și eligibile. Autorul selectează cel puțin unul. Serverul capturează versiunile și metadatele aprobate într-un `ShareSnapshot` imuabil, cu versiune de schemă. Linkul și codul trimit la același pachet, neindexat într-un catalog public.

| Se transferă | Nu se transferă |
| --- | --- |
| Titlul și descrierea aprobate în previzualizare | Mesaje, sesiuni, istoricul chatului și checkpointuri |
| Fișierele/textul selectat și versiunile fixate | Memorie AI, rezumate de conversație și notițe personale |
| Numele locale, ordinea, clasa și disciplina | Insight-uri personale, flashcard-uri, quiz-uri și audio generat |
| Metadatele necesare atribuirii și drepturilor | Profilul/emailul contului autorului, membri sau permisiuni originale |
| Referințe interne la procesare compatibilă, numai pe server | Chei, tokenuri, secrete, configurații, căi de filesystem sau referințe de chat |

Câmpurile transferate sunt o listă explicită permisă, nu serializarea generică a carnetului. Fișierele însele pot conține nume sau alte date: excluderea profilului autorului nu anonimizează automat documentele. Previzualizarea explică această diferență.

Copierea nu cere reextragere sau un apel LLM dacă procesarea compatibilă este disponibilă. Artefactele neutre pot fi reutilizate intern; rezultatele AI personale nu se propagă astfel.

### 8.2 Importul și atomicitatea

1. Destinatarul autentificat introduce linkul sau codul.
2. Serverul validează pachetul și permite doar previzualizarea metadatelor aprobate.
3. „Importă în Carnetele mele” verifică din nou starea, drepturile, disponibilitatea materialelor și cotele.
4. O tranzacție creează carnetul, asocierile locale și înregistrarea importului.
5. Se afișează succes numai după crearea completă. Copia are zero notițe, mesaje și memorie personală.

La eșec nu apare o copie prezentată drept completă. Operațiile de stocare/joburi din afara tranzacției folosesc pregătire, reluare și curățare compensatorie, nu o promisiune de tranzacție comună PostgreSQL–filesystem–furnizor AI.

Cheia de idempotency este asociată destinatarului, operației și payloadului: repetarea aceleiași solicitări întoarce aceeași copie; reutilizarea cheii cu alt payload este respinsă. O importare nouă, intenționată, cu altă cheie poate crea o altă copie. Nu se impune unicitate permanentă pe perechea utilizator–pachet.

### 8.3 Independență, revocare și concurență

- Destinatarul modifică, șterge sau redistribuie materialele eligibile din propria copie.
- Modificările originalului nu schimbă pachetul sau copiile. Pentru materiale actualizate se creează alt pachet.
- Revocarea dezactivează împreună linkul și codul; nu șterge și nu blochează copiile existente.
- Verificarea finală a stării pachetului și înregistrarea importului se serializează cu revocarea. Dacă revocarea este confirmată înainte de finalizarea importului, importul nu se finalizează. Dacă importul a fost finalizat primul, copia rămâne.
- Reîncercarea după timeout a unui import deja finalizat poate întoarce copia proprie chiar dacă pachetul a fost revocat între timp; nu este un import nou.
- Un material eliminat doar din carnetul autorului rămâne referit de snapshotul activ. Fișierul nu se pierde la curățarea stocării.
- Codurile/linkurile sunt secrete de acces la pachet, nu dovezi de identitate. Se folosesc valori aleatorii, limitarea încercărilor, stocare protejată și redactare în loguri.
- Expirarea și limitele de import sunt opționale. Politica inițială trebuie documentată, fără expirare ascunsă sau efect retroactiv asupra copiilor.

## 9. Model conceptual comun

Denumirile de mai jos sunt folosite în toate documentele. Detaliile SQL și ID-urile se stabilesc în ADR, nu prin copierea schemei SurrealDB.

| Entitate | Responsabilitate și relații |
| --- | --- |
| User | Identitate verificată, stare și roluri. |
| DigitalNotebook | Proprietar, titlu, stare, origine, versiune de șablon/pachet și context_revision. |
| SourceAsset | Octeți/text imuabil, hash, locație privată, tip și dimensiune; nu acordă singur drept de acces. |
| MaterialVersion | SourceAsset și metadate de proveniență/atribuire/drepturi versionate. |
| NotebookSource | Asociere personală cu DigitalNotebook și MaterialVersion; ID propriu, nume local și ordine. |
| ProcessingArtifact / Chunk / Embedding | Extracție și fragmente pentru MaterialVersion, versiuni parser/chunker/model, dimensiune vectorială și poziții. |
| Template / TemplateVersion / TemplateMaterial | Catalog, versiune publicată imuabilă și manifest de MaterialVersion. |
| ShareSnapshot / ShareMaterial | Autor, stare, tokenuri protejate, versiune de schemă și manifest fix. |
| ShareImport | Destinatar, snapshot, carnet creat și idempotency; nu oferă autorului acces la copie. |
| ChatSession / ChatMessage / Citation | Carnet, revizie de context, mesaje și referințe la NotebookSource/versiune/fragment. |
| Note / SourceInsight | Conținut personal și proveniență; fără copiere implicită în snapshot. |
| ProcessingJob / OutboxEvent | Operație, actor, țintă, revizie, stare, încercări și eveniment pentru worker. |
| AuditEvent | Acțiune, actor și rezultat, cu minimum de date și fără secrete/conținut personal implicit. |

MaterialVersion este necesară pentru a păstra conținutul și drepturile unui snapshot chiar după înlocuirea unei surse personale. „NotebookMaterial” și „SharePackage” din documentele vechi corespund aici NotebookSource și ShareSnapshot; nu sunt tabele suplimentare.

### Invariante de date

1. Proprietatea resurselor derivate se moștenește prin carnet și se verifică înainte de acces. Dacă se denormalizează owner_id, constrângerile previn relații cu proprietari incompatibili.
2. Copiile primesc ID-uri locale noi; citările se rezolvă prin asocierea destinatarului, nu prin ID-ul sursei personale a autorului.
3. Deduplicarea nu reprezintă autorizare și nu divulgă existența fișierelor altcuiva. Hashul trimis de client nu dovedește dreptul de acces.
4. Reutilizarea procesării cere compatibilitate de parser, segmentare, model/dimensiune embedding și domeniu de reutilizare autorizat. Cache-urile de răspuns și memoria personală nu se partajează.
5. Căutarea filtrează carnetul și materialele înainte de a livra fragmente către model. Nu se bazează exclusiv pe eliminarea ulterioară a rezultatelor străine.
6. Fișierele se șterg fizic numai când nu mai există referințe valide din carnete, versiuni de șabloane, snapshoturi ori joburi și retenția permite. Curățarea se coordonează cu importurile în curs.
7. Cota utilizatorului ia în calcul materialele logice importate, indiferent de deduplicarea fizică; bugetul AI se consumă numai pentru procesare/generare executată.
8. Joburile refuză rezultate pentru ținte șterse sau revizii depășite. Mesajele întârziate nu pot recrea accesul la surse eliminate.

## 10. Calitate, operare și protecția elevilor

Conturile, stocarea, streamingul, căutarea, joburile și checkpointurile trebuie testate pentru acces încrucișat. Setările tehnice sunt rezervate administratorilor în API, nu doar ascunse în meniu. Importurile externe amânate sunt dezactivate și pe server.

Limitele de fișiere, pagini, carnete, joburi și cereri AI sunt configurabile. Valorile se stabilesc înainte de staging/pilot pe baza capacității și bugetului. Erorile sunt în română și nu expun secrete. Interfața funcționează pe telefon și calculator, prin tastatură, cu contrast și etichete verificate.

Se prevăd validarea încărcărilor, raportarea conținutului, minimizarea datelor, retenția, ștergerea contului, exportul datelor personale și auditul accesului administrativ. Exportul pentru confidențialitate este separat de share-ul de materiale. Documentul nu fixează praguri juridice de vârstă sau temeiuri legale; acestea se stabilesc cu responsabilii înainte de elevi reali.

Backupul acoperă PostgreSQL, fișierele, configurația recuperabilă și secretele necesare decriptării. Restaurarea se probează într-un mediu separat. RPO, RTO, disponibilitatea, latența și costul acceptabil au valori convenite înainte de pilot; nu se deduc din demo.

## 11. Criterii de acceptare

| ID | Scenariu | Rezultat verificabil |
| --- | --- | --- |
| A01 | Vizitatorul deschide catalogul | Vede numai șabloane publicate; nu vede materiale personale. |
| A02 | Doi utilizatori pornesc același șablon | Carnete cu ID-uri diferite, asocieri locale distincte și aceleași versiuni inițiale. |
| A03 | A elimină un material din copie | Șablonul, snapshotul activ și copia B rămân valide. |
| A04 | A încarcă un fișier | B nu îl vede prin liste, ID, download, hash, căutare sau citare. |
| A05 | A începe din nou | Copie nouă din ediția publicată curentă indicată în UI; carnetul vechi rămâne. |
| A06 | Carnet gol | Zero materiale, notițe, mesaje și memorie personală. |
| A07 | Share din carnet cu chat/notițe | Pachetul respectă lista permisă; zero activitate personală implicită. |
| A08 | Import prin link și prin cod | Aceleași versiuni de materiale, proprietar nou, activitate personală goală. |
| A09 | Autorul schimbă originalul | Snapshotul și copiile nu se modifică. |
| A10 | Autorul revocă | Importuri noi respinse; copiile anterioare rămân accesibile destinatarilor. |
| A11 | Acces direct la resursele altuia | Refuz server inclusiv în worker, streaming, checkpoint și export. |
| A12 | Răspuns cu citare | Referința este autorizată, existentă și verificată pentru susținerea afirmației. |
| A13 | Întrebare fără răspuns în surse | Lipsa informației este declarată, fără citări inventate. |
| A14 | Se publică o ediție nouă | Copiile existente nu se actualizează; instanțierile noi fixează ediția nouă. |
| A15 | Retry/dublu click | O copie per cheie de operație; importarea intenționată nouă este permisă. |
| A16 | Import/procesare eșuată | Niciun succes fals sau carnet incomplet ascuns; retry și curățare controlate. |
| A17 | Eliminare/schimbare selecție după chat | Context nou; memoria, cache-ul și răspunsul în curs nu reintroduc vechile surse. |
| A18 | Ștergere carnet cu fișiere deduplicate | Copiile și snapshoturile cu referințe valide păstrează fișierele. |
| A19 | Revocare simultană cu import | Rezultatul respectă ordinea tranzacțională din §8.3. |
| A20 | Cota este depășită la import | Refuz înainte de finalizare, fără copie parțială sau ocolire prin deduplicare. |
| A21 | Material înlocuit/reprocesat | Snapshoturile rămân pe versiunea fixată; jobul vechi nu suprascrie versiunea nouă. |
| A22 | Restaurare backup | Proprietatea, pachetele revocate, fișierele și chatul se păstrează corect. |
| A23 | Elevul apelează rute administrative | Refuz server chiar dacă URL-ul este cunoscut. |
| A24 | PDF scanat fără OCR | Stare explicată; nu este publicat sau prezentat ca material AI gata. |
| A25 | Fișier cu text de tip instrucțiune ostilă | Nu schimbă permisiuni, nu accesează alte carnete și nu declanșează instrumente nepermise. |
| A26 | Notebook mare/model indisponibil | Limite și eroare controlate; contextul nu este tăiat în tăcere cu răspuns înșelător. |
| A27 | Refacere index cu alt model | Vectorii incompatibili nu se amestecă; noul index devine activ numai după verificare. |
| A28 | Ștergere cont autor | Linkurile active sunt revocate; copiile destinatarilor rămân independente. |

Izolarea are criteriu de acceptare zero acces neautorizat în suita de scenarii; aceasta nu echivalează cu o demonstrație formală de absență a tuturor vulnerabilităților. Pragurile pentru calitatea AI, cost și latență se fixează înainte de evaluarea pilotului.

## 12. Ordinea livrării și deciziile încă necesare

1. Inventar, copii de siguranță ale datelor locale și configurarea fork-ului.
2. ADR-uri și fundație PostgreSQL, identitate, autorizare și worker; testele încep aici.
3. Probă completă cu doi utilizatori: carnet → PDF → procesare → căutare → chat/citare → restart.
4. Restul formatelor MVP, notițe, interfață română și administrare.
5. Șabloane versionate și copii personale.
6. Snapshoturi, import și revocare.
7. Restaurare, securitate, evaluare pedagogică și pilot.
8. Flashcard-uri, quiz-uri și prezentare audio.

Înainte de fiecare modul se închid doar alegerile care îl afectează:

| Decizie | Responsabil | Termen necesar |
| --- | --- | --- |
| Bibliotecă DB/migrații, coadă, strategie checkpointuri și identitate | Responsabil tehnic | Înainte de migrarea modulelor respective |
| Dimensiune/model embedding și limite de context | Responsabil AI/tehnic | Înainte de index și chat |
| Furnizori acceptați, buget și găzduire | Inițiator + responsabil tehnic | Înainte de folosirea serviciilor și staging |
| Clase, discipline, ediții și profesori evaluatori | Inițiator + editor de catalog | Înainte de popularea catalogului pilot |
| Accesul minorilor, retenție, moderare și drepturi | Responsabili instituționali/juridici | Înainte de date reale și publicare |
| Praguri măsurabile de calitate, cost, latență, RPO/RTO și concurență | Echipa de produs/tehnică/pedagogică | Înainte de pilot |

Alegerea Open Notebook și înlocuirea SurrealDB sunt închise. Lista de mai sus nu redeschide aceste decizii. Starea documentară „pregătit pentru implementare” nu înseamnă „pregătit pentru producție”.

## 13. Istoricul reviziei 1.0

Au fost aliniate alegerea fork-ului, formatele MVP, versiunea folosită la pornirea din nou, rolurile și nomenclatura datelor. Au fost precizate snapshotul fără rezultate personale, idempotency, concurența revocare/import, curățarea fișierelor, memoria conversațiilor și criteriile A19–A28. Notele oficiale, organizațiile și instrumentele educaționale ulterioare nu sunt adăugate ca obligații MVP.
