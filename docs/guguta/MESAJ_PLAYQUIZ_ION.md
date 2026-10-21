Salut, Ion!

Trecem legătura Guguță ↔ PlayQuiz pe play-quiz.com.
Fluxul: elevul apasă „Deschide în PlayQuiz” pe un quiz grilă din Guguță; noi, server-la-server,
îi creăm contul in play-quiz, urcăm quizul și îl deschidem deja autentificat pe quiz.

Planul cu exemple JSON: https://github.com/mariuscerescu/Platform-Guguta/blob/main/docs/guguta/PLAN_INTEGRARE_PLAYQUIZ_COM.md

Ce avem nevoie de la voi:

1) Cont de partener, fără parolă: POST /api/partner/guguta/accounts
   {external_id (UUID Guguță), email, display_name, language: "RO"} → {account_id, created}.
   Idempotent pe external_id.
2) Quiz în numele unui cont: POST /api/partner/guguta/quizzes
   {external_id (UUID quiz), account_external_id, title, language, quiz_type: SINGLE_CHOICE | MULTIPLE_CHOICE,
   category, time_per_question, content_hash, questions: [{content, answers[], wrong_answers[]}]}
   → {quiz_id, play_url, updated}. Idempotent pe external_id + content_hash.
3) Handoff (autologin): POST /api/partner/guguta/handoff {account_external_id, quiz_id} → {url, expires_in}.
   URL-ul duce la o pagină /handoff?token=… care schimbă tokenul de unică folosință pe sesiunea JWT
   și redirecționează la quiz.
4) Autentificarea noastră: Authorization: Bearer <cheie de partener>; opțional semnătură HMAC.
5) O categorie „Guguță” (sau lista categoriilor voastre pe discipline, ca să mapăm).

Punctul 1 se poate refolosi din ramura locală feat/guguta-integration (GugutaAccounts + migrarea de identitate).
Noi facem partea Guguță în paralel, cu serverul vostru simulat în teste, și conectăm pe staging când sunteți gata.

Mulțumesc,
Tudor
