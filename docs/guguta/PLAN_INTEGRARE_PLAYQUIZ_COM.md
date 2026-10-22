# Guguță → PlayQuiz: contractul implementat

Actualizat la 22.10.2026 după verificarea surselor și a OpenAPI din VM-ul
`johny-playquiz`: EduPlatform-BE `develop` / `e39a0c3` și PlayQuiz-FE
`development` / `2962850`. Codul Guguță este pregătit; activarea așteaptă cheia.

## Fluxul efectiv

1. Elevul deschide un quiz grilă și apasă „Deschide în PlayQuiz”.
2. La primul export acceptă transmiterea numelui afișat, emailului, ID-ului
   extern și întrebărilor către PlayQuiz. Parola Guguță nu se transmite.
3. API-ul Guguță creează quizul, salvează linkul și tokenul, apoi cere contul
   și linkul de login. Browserul primește numai acest link.
4. PlayQuiz cere o parolă la prima intrare. La următoarele accesări schimbă
   tokenul de unică folosință pe sesiunea sa și deschide `/quiz/custom/{id}`.

Quizul rămâne jucabil în Guguță. Doar quizurile gata, alcătuite integral din
`multiple_choice` / `multiple_select`, au butonul de export. El rămâne vizibil
și înainte de configurare; fără cheie API-ul răspunde `playquiz_disabled`.

## Autentificare server-la-server

Header: `X-Partner-Key: <cheia emisă de PlayQuiz>`.

Nu se folosește Bearer, HMAC sau un endpoint separat `/handoff`.
Nu se urmăresc redirectări cu cheia. Linkurile returnate sunt acceptate numai
pe originea configurată, în rutele `/partners/play/{UUID}` și `/login`.
Tokenurile de login și cheia nu se jurnalizează sau persistă în exporturi.

## 1. Crearea quizului

`POST https://play-quiz.com/api/partner/quizzes`

```json
{
  "quizType": "SINGLE_CHOICE",
  "timePerQuestion": 30,
  "questions": [
    {"content": "Cât fac 3 + 4?", "answers": ["7"], "wrongAnswers": ["6", "8"]}
  ]
}
```

Răspuns:

```json
{"playUrl":"https://play-quiz.com/partners/play/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
```

- Toate întrebările single → `SINGLE_CHOICE`; dacă există multi-select sau
  mai multe răspunsuri corecte → `MULTIPLE_CHOICE`.
- Maximum 50 de întrebări și 10 variante în total pe întrebare; minimum un
  răspuns corect și unul greșit. Enunțurile/variantele au maximum 1000 caractere.
  Conținutul prea lung este refuzat cu mesaj, nu trunchiat.
- Timp: easy 40 s, medium 30 s, hard 20 s.
- Titlul, clasa, disciplina, categoria, `external_id` și `content_hash` nu fac
  parte din acest request. API-ul actual creează un quiz personalizat fără
  clasificare în catalogul normal. Indiciile și dovezile rămân în Guguță.

## 2. Contul și autentificarea

`POST https://play-quiz.com/api/partner/guguta/accounts`

```json
{
  "external_id": "UUID-ul-utilizatorului-Guguta",
  "email": "elev@example.md",
  "display_name": "Ana Popescu",
  "language": "RO",
  "play_token": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
}
```

Răspuns (201 pentru cont nou, 200 pentru cont existent al partenerului):

```json
{
  "account_id": 123,
  "created": true,
  "password_set": false,
  "login_url": "https://play-quiz.com/login?partner=TOKEN_UNIC&play=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "login_expires_in": 900
}
```

Emailul este obligatoriu. `class_level` este opțional în PlayQuiz, dar nu este
trimis în această versiune pentru a păstra acordul existent limitat la nume și email.
Contul se identifică prin `(partner, external_id)`. Dacă emailul aparține deja
unui cont PlayQuiz fără legătură cu Guguță, API-ul refuză asocierea. Guguță
arată un mesaj și linkul salvat al quizului: elevul intră cu parola contului
său PlayQuiz. Conturile nu se unesc automat pe baza emailului.

Frontendul PlayQuiz face GET/POST `/auth/partner-login/{token}` și apoi
POST `/api/partner/quizzes/{play_token}/join`; aceste operații îi aparțin lui.

## Reutilizare și erori

PlayQuiz nu implementează idempotență pentru crearea quizurilor. Guguță:

- calculează local hashul payloadului exact, inclusiv timpul pe întrebare;
- reține `play_token` și `play_url` imediat după crearea quizului;
- refolosește tokenul când conținutul nu s-a schimbat, cerând doar alt login;
- salvează linkul chiar dacă solicitarea contului eșuează;
- folosește un lock PostgreSQL pentru clickuri simultane în procese diferite;
- nu repetă automat POST-uri după timeout, redirect sau eroare de server.

După modificarea conținutului se creează o versiune nouă în PlayQuiz. Nu există
endpoint de actualizare/ștergere pentru partener în contractul actual. Dacă
PlayQuiz creează quizul dar răspunsul se pierde înainte de salvarea tokenului,
un retry manual poate crea un duplicat; rezolvarea completă necesită
idempotență server-side în PlayQuiz. Un `Idempotency-Key` ignorat nu rezolvă asta.

Migrarea `0026` adaugă `play_token` și permite un export încă fără cont.
Coloana istorică `playquiz_quiz_id` rămâne nullable; tokenul nu este ID numeric.

## API-ul Guguță

- `GET /api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz`: disponibilitate, acord,
  exportabilitate și link salvat.
- `GET …/playquiz/payload`: requesturile exacte, în ordinea actuală; fără
  apeluri externe. La reutilizare arată numai requestul contului.
- `POST …/playquiz` cu `{"consent": true}` prima dată, apoi `{}`:
  `{url, play_token, play_url, created, updated}`.

Toate operațiile sunt autentificate și respectă RLS și CSRF existente.

## Activare

Guguță:

```dotenv
GUGUTA_PLAYQUIZ_API_URL=https://play-quiz.com/api
GUGUTA_PLAYQUIZ_PARTNER_KEY=
GUGUTA_PLAYQUIZ_TIMEOUT_SECONDS=10
```

Pe server este pregătit fișierul privat (0600):
`/home/jupyter-tudor/integrations/guguta-playquiz-contract-20261022/runtime/playquiz.env`.
URL-ul este completat, doar cheia lipsește. Nu folosi fișierul vechi al
rolloutului `guguta-playquiz-export-20261022` pentru această versiune.

PlayQuiz: aceeași cheie trebuie activată de Ion în containerul backend prin
`PARTNER_KEYS=guguta:<cheie>`; dacă există alți parteneri, lista se păstrează.
Fișierul env nu este suficient dacă variabila nu este transmisă containerului.

Pachetul local conține `deploy.py` cu pașii `build`, `check`, `up`. Folosește
întregul lanț Compose activ al API-ului, adaugă ultimul override și nu schimbă
serviciile AI sau bazele. `up` refuză cheia goală, rulează migrarea cu imaginea
nouă și recreează numai API, worker, frontend. Restart simplu nu recitește env.
Deploy-ul și proba reală se fac după activarea cheii la ambele capete.

Validare înainte de activare: teste de contract cu API simulat, PostgreSQL
izolat (migrare, RLS, reluare după eșec, clickuri simultane), TypeScript și
buildul frontend. Nu se exportă date reale pentru aceste verificări.

Integrarea locală veche nu se dezafectează până la validarea fluxului extern.
Rezultatele înapoi și clasificarea pe discipline/clase rămân etape separate.
