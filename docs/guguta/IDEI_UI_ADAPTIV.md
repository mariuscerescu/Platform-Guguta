# Idei: interfață adaptată vârstei și scena vie din carnet

Stare: **propunere**, 16 octombrie 2026. Nu este specificație; descrie două
direcții de lucru pentru următoarele etape, cu suficient detaliu ca să poată fi
pornite ca sarcini separate. Comportamentul final se fixează în
[SPECIFICATII_GUGUTA.md](SPECIFICATII_GUGUTA.md) și prin ADR-uri, după prototip.

Cele două idei sunt înrudite, dar trebuie ținute **separat**: prima schimbă
*forma* interfeței în funcție de cine este elevul; a doua schimbă *conținutul*
fundalului în funcție de ce se discută acum. Au cicluri de dezvoltare, riscuri
și criterii de reușită diferite.

---

## 1. Interfață adaptată vârstei

### Problema

Interfața actuală este una singură, gândită pentru un elev de gimnaziu sau liceu
care știe să lucreze cu panouri, filtre și meniuri. Un elev din clasele primare
(I–IV) are nevoie de altceva: mai puține elemente pe ecran, text mai mare,
pictograme în locul etichetelor, culoare și mișcare, mascota mereu vizibilă,
și un singur lucru de făcut la un moment dat.

### Propunere

Trei **profiluri de interfață**, alese din clasa elevului, nu din setări tehnice:

| Profil | Clase | Ce se schimbă |
| --- | --- | --- |
| **Primar** | I–IV | O singură coloană. Carnetul se deschide direct în conversație; materialele și Studio sunt accesibile prin două butoane mari cu pictograme. Text 18–20 px, butoane mari, contrast ridicat. Guguță este permanent în ecran, cu animații de gesticulație. Vocea este modul implicit de interacțiune; dictarea pornește cu un singur buton. Fără filtre, fără meniu contextual, fără terminologie („sursă”, „șablon”). |
| **Gimnazial** | V–IX | Interfața actuală, cu trei panouri colapsabile, dar cu limbaj simplificat și cu Guguță vizibil implicit. |
| **Liceal** | X–XII | Interfața actuală, densă, cu toate instrumentele (citări afișate, Studio complet, filtre). |

Profilul se deduce din **clasa carnetului** (șabloanele din catalog au deja
clasa) și, ca valoare implicită, din profilul elevului (clasa declarată la
înregistrare). Elevul sau părintele îl poate schimba manual.

### Cum se construiește

- **Design tokens pe profil**: dimensiuni de text, spațieri, raze, densitatea
  panourilor și setul de pictograme devin variabile CSS pe `<html data-profile>`;
  temele deschisă/întunecată existente rămân ortogonale.
- **Aceleași componente, altă compoziție**: nu se scrie un al doilea frontend.
  Pagina carnetului primește un *layout* pe profil (`primar` = o coloană,
  celelalte = trei panouri), iar componentele existente (chat, materiale,
  Studio, însoțitor) se rearanjează.
- **Text pe profil**: etichetele trec printr-un mic dicționar `ro-MD` cu două
  registre („Materialele mele” vs „Surse”; „Hai să exersăm” vs „Quiz”).
- **Tonul lui Guguță**: promptul tutorelui ([ADR-017](../7-DEVELOPMENT/decisions/ADR-017-source-aware-educational-tutor.md))
  primește profilul: propoziții mai scurte, un singur pas pe mesaj, laudă
  concretă, fără abstracțiuni, pentru profilul primar.
- **Backend**: un câmp `ui_profile` pe profilul utilizatorului și pe șablon,
  expus în `/api/v1/auth/me` și în datele carnetului. Nimic altceva nu se
  schimbă în date.

### Criterii de reușită pentru prototip

- Un elev de clasa a II-a deschide un carnet „Matematică, clasa a II-a” și
  ajunge la prima întrebare prin voce fără să atingă meniuri.
- Niciun text sub 16 px în profilul primar; țintele tactile de minimum 44 px.
- Comutarea profilului nu pierde date și nu cere reîncărcarea paginii.
- Testele E2E Playwright au cel puțin un flux pe profil.

---

## 2. Scena vie: fundalul carnetului reacționează la conversație

### Ideea

Când elevul discută cu Guguță într-un carnet, zona liberă din fundal (în jurul
mascotei sau o „tablă” dedicată) nu rămâne statică. Dacă problema vorbește
despre 3 mere verzi și 3 mere roșii, merele apar pe tablă; dacă Guguță explică
fracții, apare un cerc împărțit; dacă se discută un rău din geografie, apare
harta cu râul evidențiat. Elementele pot fi mutate, numărate, grupate — tabla
devine spațiu de lucru, nu doar ilustrație.

Scopul pedagogic: concretizarea noțiunii în momentul în care este explicată,
așa cum face un învățător care desenează pe tablă în timp ce vorbește. Pentru
clasele primare este esențial; pentru gimnaziu, util la matematică, științe,
geografie, istorie.

### Delimitare față de „interfața inteligentă” generală

Direcția industriei (de exemplu interfețele generative din ChatGPT, unde modelul
construiește componente întregi de aplicație în răspuns) este mai largă: modelul
decide forma întregii interfețe. Aici propunem ceva **mai restrâns și mai sigur**:

- interfața carnetului rămâne fixă și previzibilă (vezi §1);
- modelul controlează **doar scena** (tabla), printr-un vocabular limitat de
  elemente pe care le cunoaștem dinainte;
- scena nu înlocuiește răspunsul text/voce, îl însoțește;
- nimic din scenă nu poate dezvălui soluția dacă tutorele a decis să nu o dea
  (principiul din ADR-017 și PDR-003 se aplică și la imagini).

### Trei surse pentru conținutul scenei

1. **Directive structurate emise de model** (calea principală). În timpul
   răspunsului, modelul produce, pe lângă text, instrucțiuni de scenă într-un
   format structurat (apel de instrument sau bloc JSON separat în fluxul SSE),
   de tipul: „pune 3 obiecte `apple` de culoare `green` și 3 `apple` `red` în
   două grupuri; etichetează grupurile”. Frontend-ul le randează cu o bibliotecă
   proprie de primitive. Latență mică, cost mic, deterministic, fără imagini
   generate.
2. **Scenarii pregătite din timp** per unitate de învățare. Pentru șabloanele
   din catalog (manualul clasei a II-a, capitolul „Adunarea până la 20”),
   echipa sau un job offline pregătește scene gata (obiectele, axa numerelor,
   tabla). Modelul alege scena și completează parametrii. Calitate controlată,
   potrivit pentru clasele primare.
3. **Generare de imagini în timp real** (opțional, ulterior). Pentru cazuri în
   care primitivele nu ajung („desenează o celulă vegetală”), un model de
   imagine generează ilustrația. Mai lent (secunde), cu cost și cu risc de
   erori factuale; se folosește doar cu cache pe șablon și cu revizuire.

### Vocabularul de scenă (prima versiune)

Un set mic, dar compozabil, de primitive randate în SVG/Canvas:

| Primitivă | Parametri | Exemple de utilizare |
| --- | --- | --- |
| `objects` | tip (măr, minge, carte, monedă…), culoare, număr, grupuri | numărare, adunare, scădere, mulțimi |
| `number_line` | interval, marcaje, salturi evidențiate | adunare, scădere, numere negative |
| `fraction` | întreg (cerc/dreptunghi), părți, părți colorate | fracții, procente |
| `shape` | tip, laturi, unghiuri, etichete | geometrie |
| `board_text` | text scurt, scris „de mână”, evidențieri | cuvinte, silabe, formule |
| `table` | rânduri, coloane | comparații, tabele de înmulțire |
| `timeline` | evenimente cu ani | istorie |
| `map_highlight` | regiune/râu/oraș din Republica Moldova | geografie |
| `clear` / `animate` | tranziții între stări | pași succesivi ai unei rezolvări |

Fiecare directivă are un `step` ca scena să poată fi derulată înapoi („arată-mi
din nou pasul 2”), iar elementele `objects` sunt **interactive**: elevul le
poate trage în grupuri, iar gruparea rezultată este trimisă înapoi modelului ca
răspuns nonverbal.

### Arhitectură propusă

```
model (tutore) ──► text + directive de scenă (SSE, canal separat)
                          │
              api: validare schemă, filtrare (fără soluții), persistare pe mesaj
                          │
    frontend: SceneBoard (SVG/Canvas) ──► primitive ──► animații, interacțiune
                          │
            interacțiunea elevului ──► eveniment structurat ──► model
```

- **API**: directivele se validează cu o schemă strictă (pydantic) și se
  păstrează în mesajul de chat, ca scena să fie reconstruită la redeschiderea
  conversației. Se adaugă o coloană `scene` (JSONB) pe mesaj.
- **Prompt**: tutorele primește descrierea vocabularului și regula „folosește
  scena când noțiunea este concretă; nu pune pe tablă rezultatul final înainte
  ca elevul să încerce”.
- **Frontend**: componentă `SceneBoard` montată în pagina carnetului (în zona
  liberă din profilul primar, sau ca panou în celelalte profiluri), cu
  biblioteca de primitive și o coadă de animații sincronizată cu fluxul text/voce.
- **Voce**: când conversația este vorbită ([ADR-022](../7-DEVELOPMENT/decisions/ADR-022-elevenlabs-notebook-voice.md)),
  directivele vin tot din partea noastră de server, sincronizate cu replica.

### Faze

1. **Prototip** (1–2 săptămâni): `objects`, `number_line`, `board_text`,
   `clear`; directivele emise de model în chatul text; fără persistare;
   un singur șablon („Matematică, clasa a II-a”). Măsurăm dacă modelul emite
   directive corecte și la timp.
2. **Scena ca parte a conversației**: persistare, derulare pe pași, interacțiune
   (tragere în grupuri), restul primitivelor, sincronizare cu vocea.
3. **Scenarii pregătite** pentru șabloanele din catalog; editor minimal pentru
   echipă.
4. **Generare de imagini** doar dacă fazele 1–3 arată că primitivele nu ajung.

### Riscuri și întrebări deschise

- Modelul poate emite directive incoerente cu textul; nevoie de validare și de
  un „buget” de elemente pe scenă (maximum 20 de obiecte).
- Distragere: pentru unii elevi, mișcarea permanentă dăunează. Scena trebuie să
  poată fi oprită de elev și de învățător.
- Cost: directivele adaugă tokeni la fiecare răspuns; se măsoară în faza 1.
- Accesibilitate: fiecare scenă trebuie să aibă echivalent text (citit de
  cititoarele de ecran și folosit și în răspunsul vocal).
- Unde apare scena în profilul gimnazial și liceal: panou separat, sau în locul
  panoului de materiale când conversația o cere?

---

## Legături

- [SPECIFICATII_GUGUTA.md](SPECIFICATII_GUGUTA.md) — comportamentul actual.
- [ADR-017](../7-DEVELOPMENT/decisions/ADR-017-source-aware-educational-tutor.md) — tutorele pedagogic.
- [ADR-022](../7-DEVELOPMENT/decisions/ADR-022-elevenlabs-notebook-voice.md) — vocea cu context din carnet.
- `frontend-guguta/app/components/EducationCompanion.tsx` — însoțitorul actual, punctul natural de montare pentru scenă.
