# ADR-023: PlayQuiz extern (play-quiz.com) prin export de quiz și cont automat

Data: 2026-10-21. Stare: **propus** (devine acceptat după acordul echipei PlayQuiz pe contractul de partener).

## Context

ADR-021 a integrat PlayQuiz găzduind întreaga platformă (Java, Next.js, Oracle) pe serverul nostru, sub `/edu-platform/playquiz`, cu sesiunea Guguță validată la fiecare cerere și cu un proxy Java către API-ul Guguță. Soluția dublează infrastructura, leagă două baze de date pe același server și nu folosește instanța publică a colaboratorilor, `https://play-quiz.com`. Echipa PlayQuiz este partener în proiect și poate adăuga endpointuri.

## Decizie

1. Quizurile grilă rămân afișate și jucabile nativ în Guguță.
2. Dialogul quizului primește butonul „Deschide în PlayQuiz”. La apăsare, API-ul Guguță trimite server-la-server către `play-quiz.com`: contul utilizatorului (identificat prin UUID-ul Guguță ca `external_id`, fără parolă), quizul (întrebări, răspunsuri corecte și greșite) și cere un token de handoff de unică folosință. Browserul deschide URL-ul de handoff și ajunge autentificat pe quiz.
3. Comunicarea folosește o cheie de partener emisă de PlayQuiz, ținută doar în mediul API-ului Guguță; opțional semnătură HMAC. Exporturile sunt idempotente (`external_id` + `content_hash`) și reținute în tabelul `playquiz_exports`.
4. Guguță rămâne autoritatea pentru conținutul quizului; PlayQuiz este autoritatea pentru joc, scoruri și contul de jucător. Rezultatele pot reveni în Guguță printr-un webhook semnat, într-o fază ulterioară.
5. Integrarea locală din ADR-021 (stack `guguta-playquiz`, rutele nginx `/edu-platform/playquiz*`, endpointurile `/auth/playquiz-*`, serviciul `playquiz.py`) este deprecată și se elimină după ce fluxul nou funcționează în producție. ADR-021 trece la starea „înlocuit de ADR-023”.
6. La cererea utilizatorului din 22 octombrie 2026, butonul se afișează la quizurile gata alcătuite numai din întrebări grilă, inclusiv înainte de configurarea partenerului. Capabilitatea `playquiz` raportează în continuare disponibilitatea reală a conexiunii. Fără configurare, apăsarea primește eroarea controlată `playquiz_disabled`, iar quizul rămâne jucabil aici. Primul export efectiv cere consimțământul explicit al utilizatorului pentru transmiterea numelui și a e-mailului.

Contractul de partener, maparea datelor, etapele și întrebările deschise sunt în `docs/guguta/PLAN_INTEGRARE_PLAYQUIZ_COM.md`.

Actualizare 22.10.2026: redirecționarea automată a quizurilor grilă spre instanța locală a fost eliminată, iar butonul folosește cererea POST de export. Linkul vechi din antet a fost eliminat. Endpointurile PlayQuiz și cheia de partener nu sunt încă pregătite (confirmat de utilizator); partea externă nu este declarată activă. Reîncercările HTTP păstrează același `Idempotency-Key` și nu urmează redirectări cu cheia de partener.

## Implementare

Faza 1 (partea Guguță) este în cod din 21 octombrie 2026: configurarea `GUGUTA_PLAYQUIZ_*`, migrarea `0023_playquiz_exports` (tabelele `playquiz_exports` și `playquiz_consents`, cu RLS), serviciul `api/services/guguta/playquiz_export.py` (mapare, client de partener cu reîncercări și semnătură HMAC opțională, idempotență pe `content_hash`), endpointurile `GET`/`POST /api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz`, capabilitatea `playquiz` în `/api/v1/auth/me`, butonul și dialogul de acord din dialogul quizului, testele `tests/guguta/test_playquiz_export.py` și `frontend-guguta/e2e/playquiz.spec.ts`. Endpointurile locale `/auth/playquiz-*` și serviciul `playquiz.py` au fost eliminate. Rămân: confirmarea contractului de către PlayQuiz (faza 0/2) și dezafectarea stack-ului local de pe server (faza 3).

## Consecințe

- Dispar Oracle, API-ul Java și frontendul PlayQuiz de pe serverul nostru; rămâne un singur client HTTP în API-ul Guguță.
- Apare o dependență de un serviciu extern; fluxul se degradează grațios (quizul rămâne în Guguță).
- Datele personale ale elevilor sunt transmise unui operator separat doar la acțiunea explicită a utilizatorului; termenii Guguță trebuie să o menționeze.
- Contractul depinde de echipa PlayQuiz; clientul și maparea stau într-un singur modul ca ajustările să fie ieftine.
