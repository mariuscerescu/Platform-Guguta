# Plan: integrarea cu play-quiz.com (export de quiz și cont automat)

Stare: **propunere**, 21 octombrie 2026. Înlocuiește integrarea locală descrisă în
[ADR-021](../7-DEVELOPMENT/decisions/ADR-021-playquiz-integration.md), care devine
**deprecată** (PlayQuiz găzduit pe serverul nostru sub `/edu-platform/playquiz`).
Decizia structurală este consemnată ca [ADR-023](../7-DEVELOPMENT/decisions/ADR-023-playquiz-extern-export.md)
(stare: propus, până la acordul cu echipa PlayQuiz).

---

## 1. Ce vrem

1. Quizurile cu întrebări grilă (`multiple_choice`, `multiple_select`) rămân
   afișate și jucabile **nativ în Guguță**, ca acum.
2. În dialogul quizului apare butonul **„Deschide în PlayQuiz”**.
3. La apăsare, API-ul Guguță trimite quizul (JSON) și datele utilizatorului către
   API-ul **play-quiz.com**. PlayQuiz creează automat contul (dacă nu există),
   creează quizul în contul acelui utilizator și întoarce un link de intrare.
   Utilizatorul ajunge în PlayQuiz **deja autentificat**, direct pe quiz.
4. Nu mai rulăm PlayQuiz (Java + Next.js + Oracle) pe serverul nostru.

Principii: Guguță rămâne autoritatea pentru conținutul quizului; PlayQuiz este
autoritatea pentru joc și pentru contul de jucător. Comunicarea este
**server-la-server** (API Guguță ↔ API PlayQuiz), cu o cheie de partener; browserul
elevului nu primește niciodată secrete.

---

## 2. Ce știm despre API-ul play-quiz.com (verificat 21.10.2026)

- API-ul public este la `https://play-quiz.com/api`, același cod ca repo-ul
  `EduPlatform-BE` al colaboratorilor (ramura `develop`, commit `60661bb` la data
  verificării). Nu există documentație OpenAPI publică; contractul de mai jos
  este dedus din cod și trebuie **confirmat de echipa PlayQuiz**.
- Existente și relevante:

  | Endpoint | Rol | Observații |
  | --- | --- | --- |
  | `POST /api/auth/register` | cont nou (`AccountDto`: `email`, `password`, `username`, `name`, `surname`, `birthday`, `language`) | parola este obligatorie; activare prin e-mail |
  | `POST /api/auth/login` | JWT pentru utilizator | folosit de frontendul PlayQuiz |
  | `POST /api/quiz/custom` | quiz personalizat (`CustomQuizDto`: `quizTypeId`, `questions[]{content, answers[], wrongAnswers[]}`, `timePerQuestion` 5–300 s, `categoryIds`, `invitedUserIds`) | ≤ 50 întrebări, ≤ 10 răspunsuri, ≤ 1000 caractere; creat **în numele utilizatorului autentificat** |
  | `GET /api/quiz/custom/{id}` | datele quizului pentru player | |
  | `GET /api/quiz/types` | tipuri: 1 `SINGLE_CHOICE`, 2 `MULTIPLE_CHOICE`, 3 `ONE_FROM_TWO`, 4 `INPUT`, … | public |
  | `GET /api/language/languages` | 1 EN, 2 RU, 3 DE, **4 RO** | public |
  | `GET /api/category` | categorii | necesită autentificare |

- Lipsesc (trebuie adăugate de echipa PlayQuiz):
  - un endpoint de **partener** pentru creare/actualizare de cont **fără parolă**,
    identificat prin ID-ul extern Guguță;
  - creare de quiz **în numele** unui utilizator (acum doar utilizatorul autentificat
    își poate crea quiz);
  - **handoff** (autentificare automată): un token de unică folosință, cu viață
    scurtă, care deschide PlayQuiz direct pe quiz;
  - o categorie pentru quizurile Guguță (sau categorii pe discipline).

Nota: ramura locală `feat/guguta-integration` din `EduPlatform-BE` conține deja
clasa `GugutaAccounts` (profil Oracle identificat prin UUID-ul Guguță) și migrarea
pentru identitatea Guguță; se pot refolosi la endpointul de cont.

---

## 3. Fluxul propus

```
elev (browser Guguță)                 API Guguță                         API play-quiz.com
   │  click „Deschide în PlayQuiz”        │                                     │
   │  window.open(about:blank) [sincron]  │                                     │
   ├─ POST /notebooks/{nb}/quizzes/{q}/playquiz ─►                              │
   │                                      │ 1. quiz ready, toate întrebările grilă
   │                                      │ 2. payload (mapare §5)              │
   │                                      ├─ POST /partner/guguta/accounts ────►│ cont nou sau existent (external_id)
   │                                      ├─ POST /partner/guguta/quizzes ─────►│ quiz nou / actualizat (external_id + versiune)
   │                                      ├─ POST /partner/guguta/handoff ─────►│ token de unică folosință (60 s)
   │                                      │ 3. salvează playquiz_exports        │
   │◄── 200 {url: https://play-quiz.com/handoff?token=…} ─┘                     │
   │  fereastra deschisă navighează la url ───────────────────────────────────►│ setează sesiunea, redirect la /quiz/custom/{id}
```

Detalii:

- **Idempotență**: `playquiz_exports` (tabel nou în PostgreSQL) reține
  `quiz_id`, `playquiz_quiz_id`, `playquiz_account_id`, `content_hash`,
  `exported_at`. La un nou click: dacă `content_hash` este neschimbat, nu se
  recreează quizul, doar se cere un handoff nou; dacă s-a schimbat (întrebare
  editată), se trimite o actualizare (sau o versiune nouă, după ce decide PlayQuiz).
- **Degradare**: dacă PlayQuiz nu răspunde (timeout 10 s, 2 reîncercări la 5xx),
  butonul arată o eroare scurtă; quizul rămâne jucabil în Guguță.
- **Fereastra nouă**: `window.open` se apelează sincron la click (înainte de
  `await`), altfel blocatoarele de popup o opresc; la eroare fereastra se închide.
- **Vizibilitate**: butonul apare doar când (a) capabilitatea `playquiz` din
  `/api/v1/auth/me` este activă (variabilele de mediu setate) și (b) quizul are
  numai întrebări grilă. Quizurile mixte rămân doar în Guguță (ca în ADR-021).

---

## 4. Contractul de partener propus (de negociat cu echipa PlayQuiz)

Toate apelurile sunt server-la-server, HTTPS, JSON, cu antetele:

```
Authorization: Bearer <cheie de partener emisă de PlayQuiz pentru Guguță>
X-Guguta-Timestamp: <unix seconds>
X-Guguta-Signature: HMAC-SHA256(secret, timestamp + "." + corp)   # opțional, dacă PlayQuiz vrea semnătură
Idempotency-Key: <uuid>                                            # pentru POST-urile de creare
```

### 4.1 `POST /api/partner/guguta/accounts`

Cerere:

```json
{
  "external_id": "4e4b8f2a-…",        // UUID-ul utilizatorului Guguță (cheie de identitate)
  "email": "elev@exemplu.md",
  "display_name": "Ana Popescu",
  "language": "RO",
  "class_level": "VII"                // opțional
}
```

Răspuns: `{"account_id": 1234, "created": true}`. Idempotent pe `external_id`;
la apel repetat actualizează numele/e-mailul. Fără parolă; contul nu poate fi
folosit cu login clasic decât dacă utilizatorul își setează ulterior o parolă în
PlayQuiz („Am venit din Guguță”).

### 4.2 `POST /api/partner/guguta/quizzes`

```json
{
  "external_id": "quiz-uuid-din-guguta",
  "account_external_id": "4e4b8f2a-…",
  "title": "Fracții – recapitulare",
  "language": "RO",
  "quiz_type": "SINGLE_CHOICE",       // sau MULTIPLE_CHOICE (vezi §5)
  "category": "guguta",                // sau id de categorie convenit
  "time_per_question": 30,
  "content_hash": "sha256:…",
  "questions": [
    {"content": "Cât fac 3 + 4?", "answers": ["7"], "wrong_answers": ["6", "8", "12"]},
    {"content": "Care sunt numere pare?", "answers": ["2", "8"], "wrong_answers": ["3", "9"]}
  ]
}
```

Răspuns: `{"quiz_id": 5678, "play_url": "https://play-quiz.com/quiz/custom/5678", "updated": false}`.
Idempotent pe `external_id` + `content_hash`.

### 4.3 `POST /api/partner/guguta/handoff`

`{"account_external_id": "…", "quiz_id": 5678}` →
`{"url": "https://play-quiz.com/handoff?token=…", "expires_in": 60}`.
Tokenul este de unică folosință; pagina `/handoff` din frontendul PlayQuiz îl
schimbă pe sesiunea JWT obișnuită și redirecționează la quiz.

### 4.4 (faza 4, opțional) rezultate înapoi

PlayQuiz → Guguță: `POST https://tineri.math.md/edu-platform/guguta-api/api/v1/integrations/playquiz/results`
cu `{quiz_external_id, account_external_id, score, correct, total, played_at}`,
semnat cu aceeași cheie. Guguță înregistrează o încercare marcată `source=playquiz`.

### Varianta minimă (dacă PlayQuiz nu poate adăuga endpointuri)

Guguță folosește `POST /api/auth/register` cu o parolă aleatoare, apoi
`POST /api/auth/login` pentru JWT și `POST /api/quiz/custom` cu acel JWT;
deschiderea în PlayQuiz cere ca frontendul lor să accepte tokenul (de exemplu în
fragmentul URL). **Nu este recomandată**: ar obliga Guguță să păstreze parole
pentru conturi străine și depinde de activarea prin e-mail. Este acceptabilă
doar pentru o demonstrație.

---

## 5. Maparea datelor

| Guguță | PlayQuiz | Regulă |
| --- | --- | --- |
| `quiz.title` (sau „Quiz: <carnet>”) | `title` | ≤ 200 caractere |
| carnetul: disciplină / clasă (din șablonul de catalog) | `category` | o categorie „Guguță” la început; pe discipline în faza 4 |
| toate întrebările `multiple_choice` | `quiz_type = SINGLE_CHOICE` | |
| cel puțin o `multiple_select` | `quiz_type = MULTIPLE_CHOICE` | de confirmat că PlayQuiz acceptă amestec în același quiz |
| `question.prompt` | `content` | ≤ 1000 caractere; se taie cu avertisment în jurnal |
| `options[is_correct=true].text` | `answers[]` | 1 pentru single, ≥ 1 pentru multiple |
| `options[is_correct=false].text` | `wrong_answers[]` | ≤ 10 în total |
| `question.hint`, `concepts`, `evidence`, `explain` | nu se trimit | rămân în Guguță; eventual `hint` în faza 4 |
| `quiz.difficulty` | `time_per_question` | easy 40 s, medium 30 s, hard 20 s (valori de pornire) |
| > 50 de întrebări | refuz cu mesaj | sau se trimit primele 50 (de decis) |
| `user.id` | `external_id` | UUID Guguță, cheia de identitate |
| `user.email`, `user.display_name` | `email`, `display_name` | vezi datele personale mai jos |

**Datele personale ale elevilor.** Elevii sunt în mare parte minori. Trimitem
minimul necesar (ID extern, e-mail, nume afișat, limba). Înainte de a activa
funcția în producție: (a) mențiune în termenii Guguță că la apăsarea butonului
datele sunt transmise către PlayQuiz (operator separat) și (b) consimțământ
explicit la primul export („Trimit numele și e-mailul meu către PlayQuiz”). De
discutat cu PlayQuiz dacă acceptă un e-mail pseudonim (`<uuid>@guguta.tineri.math.md`)
pentru conturile venite din Guguță.

---

## 6. Schimbări în Guguță

### Backend (`api/`, `open_notebook/`, `alembic/`)

- Configurare: `GUGUTA_PLAYQUIZ_API_URL`, `GUGUTA_PLAYQUIZ_PARTNER_KEY`,
  `GUGUTA_PLAYQUIZ_HMAC_SECRET` (opțional), `GUGUTA_PLAYQUIZ_CATEGORY`,
  `GUGUTA_PLAYQUIZ_TIMEOUT_S=10`. Documentate în `.env.guguta.example` și
  `deploy/edu-platform/.env.example`. Capabilitatea `playquiz` în `/api/v1/auth/me`
  este activă doar când URL-ul și cheia sunt setate.
- Serviciu nou `api/services/guguta/playquiz_export.py`: client `httpx` cu
  timeout și reîncercări, maparea din §5, `content_hash`, idempotență,
  jurnalizare fără date personale.
- Migrare Alembic `0023_playquiz_exports`: tabel `playquiz_exports`
  (`quiz_id` FK, `playquiz_quiz_id`, `playquiz_account_id`, `content_hash`,
  `exported_at`, `last_handoff_at`), RLS pe utilizator ca la `quizzes`.
- Endpoint `POST /api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz` → `{url, quiz_id, created}`;
  `GET …/playquiz` → starea exportului (pentru a afișa „Deschide din nou”).
- Se elimină: `GET /auth/playquiz-profile`, `GET /auth/playquiz-quizzes`,
  `api/services/guguta/playquiz.py` (toate deservesc integrarea locală).
- Teste în `tests/guguta/`: mapare (single/multiple/mixt/limite), idempotență,
  eroare PlayQuiz, capabilitate inactivă; serverul PlayQuiz este simulat cu
  `respx`.

### Frontend (`frontend-guguta/`)

- Butonul „Deschide în PlayQuiz” în dialogul quizului (`app/notebook/[id]/page.tsx`),
  cu stări: inactiv (capabilitate lipsă sau întrebări non-grilă, cu tooltip),
  „Se trimite…”, succes (fereastra nouă), eroare (mesaj scurt). Prima apăsare
  arată dialogul de consimțământ (§5), reținut pe utilizator.
- Se elimină linkul `PlayQuiz` din `SiteHeader.tsx` (sau devine „Contul meu
  PlayQuiz” prin handoff fără quiz, faza 4) și lista albă `/playquiz` din
  `app/login/page.tsx`.
- Test Playwright: butonul lipsește fără capabilitate; cu API simulat, apăsarea
  deschide URL-ul primit.

### Dezafectarea integrării locale (pe server, după ce fluxul nou merge)

1. nginx: scoate `location /edu-platform/playquiz/` și `/edu-platform/playquiz-api/`.
2. Oprește stack-ul Docker `guguta-playquiz` (`runtime/compose.yml`), păstrează
   export Oracle în `runtime/backups`, apoi șterge volumul.
3. Ramurile locale `feat/guguta-integration` din `PlayQuiz-FE` / `EduPlatform-BE`
   se etichetează (`archive/guguta-local-2026-10`) și nu se mai publică.
4. ADR-021 trece la starea „înlocuit de ADR-023”; `README.md` și
   `SPECIFICATII_GUGUTA.md` se actualizează.

---

## 7. Schimbări la PlayQuiz (echipa play-quiz.com)

1. Modul `partner` (de exemplu `com.play.quiz.partner`) cu cheie de partener
   configurată prin variabile de mediu și, opțional, verificare HMAC.
2. Cont cu `external_id` (coloană pe `accounts`, unică pe partener) și fără parolă;
   refolosire `GugutaAccounts` din ramura locală.
3. Creare/actualizare de quiz personalizat pentru un cont dat, cu `external_id`
   și `content_hash` (idempotență), plus categoria „Guguță”.
4. Handoff: endpoint care emite token de unică folosință și pagina `/handoff`
   în frontend care îl schimbă pe sesiune și redirecționează la quiz.
5. Traduceri RO pentru playerul de quiz personalizat (dacă lipsesc).
6. (faza 4) Webhook de rezultate către Guguță.

---

## 8. Întrebări pentru echipa PlayQuiz (de trimis odată cu acest document)

1. Acceptați endpointurile de partener din §4? Dacă nu, ce alternativă propuneți?
2. Autentificarea partenerului: cheie statică, HMAC, mTLS sau listă de IP-uri?
3. Ce categorie folosim pentru quizurile Guguță? Există categorii pe discipline
   și clase pe care le-am putea mapa?
4. Puteți adăuga pagina `/handoff` cu token de unică folosință?
5. Limitele din `CustomQuizDto` (50 întrebări, 10 răspunsuri, 1000 caractere)
   rămân? Un quiz poate amesteca întrebări single și multiple?
6. Date de cont: e-mailul este obligatoriu? Acceptați e-mail pseudonim pentru
   elevi minori? `birthday` poate lipsi?
7. Doriți să trimiteți rezultatele înapoi în Guguță (faza 4)?
8. Aveți un mediu de test (staging) și chei de test pentru noi?
9. Cum tratați re-exportul: actualizare în loc sau quiz nou cu versiune?

---

## 9. Etape și responsabili

| Faza | Conținut | Cine | Durată estimată |
| --- | --- | --- | --- |
| 0 | Acord pe contract (§4) și răspunsuri la §8; ADR-023 trece la „acceptat” | Tudor + echipa PlayQuiz | 1 săptămână |
| 1 | Guguță: serviciul de export, migrarea, endpointul, butonul, capabilitatea, teste cu server simulat. Se poate face în paralel cu faza 0, pe contractul propus; se ajustează după răspunsuri | sesiune cloud (prompt în [PLAN_SESIUNI_CLOUD.md](PLAN_SESIUNI_CLOUD.md), sarcina 7) | 1–2 săptămâni |
| 2 | PlayQuiz: endpointurile de partener pe staging; test cap-la-cap cu chei de test; apoi producție | echipa PlayQuiz + Tudor | 2 săptămâni |
| 3 | Dezafectarea integrării locale (§6) | pe server (local, Codex sau manual) | 1 zi |
| 4 | Rezultate înapoi, categorii pe discipline, re-export cu versiuni, „Contul meu PlayQuiz” | ambele echipe | ulterior |

---

## 10. Riscuri

- **Serviciu extern indisponibil**: butonul se degradează grațios; quizul rămâne
  jucabil în Guguță. Se monitorizează rata de eșec a exporturilor.
- **Date personale ale minorilor**: minimizare, consimțământ la primul export,
  eventual pseudonimizare; se consemnează în termeni.
- **Duplicate**: idempotență pe `external_id` + `content_hash`, `Idempotency-Key`.
- **Divergență de conținut** după editarea unei întrebări în Guguță: re-export
  cu hash nou; PlayQuiz decide actualizare sau versiune nouă.
- **Contract neconfirmat**: faza 1 se construiește pe contractul propus, cu
  maparea și clientul izolate într-un singur modul, ca ajustările să fie ieftine.
- **Blocatoare de popup**: fereastra se deschide sincron la click.
