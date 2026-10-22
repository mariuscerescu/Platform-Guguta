# ADR-023: PlayQuiz extern prin export de quiz și cont de partener

Data: 2026-10-21. Actualizat: 2026-10-22.
Stare: **acceptat**, adaptat la implementarea verificată în EduPlatform-BE
`e39a0c3`; activarea în producție așteaptă cheia de partener.

## Context

PlayQuiz rulează separat în VM și pe play-quiz.com. Păstrăm quizurile Guguță
native și oferim „Deschide în PlayQuiz” numai pentru întrebări grilă.
Contractul propus inițial cu Bearer, upsert și `/handoff` a fost înlocuit cu
contractul efectiv al echipei PlayQuiz, verificat în surse și în OpenAPI live.

## Decizie

1. `POST /api/partner/quizzes` cu `X-Partner-Key` creează quizul. Folosim
   `quizType`, `timePerQuestion`, `content`, `answers`, `wrongAnswers`.
2. Salvăm `playUrl` și tokenul lui, apoi apelăm
   `POST /api/partner/guguta/accounts` cu `external_id`, email, nume, RO și
   `play_token`. `login_url` este de unică folosință, valabil 15 minute.
3. La prima accesare PlayQuiz cere alegerea unei parole; ulterior intrarea din
   Guguță este automată. Parolele celor două platforme nu se sincronizează.
   Emailul deja înregistrat independent nu se asociază automat: afișăm linkul
   quizului pentru autentificarea elevului în contul existent.
4. Acord explicit înainte de transmitere; cheia numai server-side, fără
   redirectări HTTP și cu validarea originii/rutei linkurilor returnate.
5. Hash local al payloadului, token persistat înainte de login și lock între
   procese pentru reutilizare. Nu repetăm automat POST-uri: PlayQuiz nu
   deduplică. Nu promitem exact-once dacă răspunsul de creare se pierde.
6. Migrarea `0025` permite salvarea tokenului fără cont încă asociat. RLS-ul
   rămâne pe utilizator; datele existente se păstrează.
7. URL-ul poate fi preconfigurat cu cheia goală: capabilitatea rămâne falsă.
   Butonul grilă rămâne vizibil și raportează indisponibilitatea controlat.

## Consecințe

Quizurile exportate sunt personalizate (`/quiz/custom/...`), fără titlu/categorie
în contractul actual. Clasificarea pe clase/discipline și întoarcerea scorurilor
necesită extindere PlayQuiz. Schimbarea conținutului creează o versiune nouă.
Integrarea locală din ADR-021 se păstrează până la validarea celei externe.

Contract, exemple și procedura de activare:
[PLAN_INTEGRARE_PLAYQUIZ_COM.md](../../guguta/PLAN_INTEGRARE_PLAYQUIZ_COM.md).
