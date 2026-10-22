Salut, Ion!

Am verificat implementarea de pe develop (e39a0c3) și am adaptat Guguță:
POST /api/partner/quizzes cu X-Partner-Key → playUrl, apoi
POST /api/partner/guguta/accounts cu play_token → login_url.
Păstrăm tokenul quizului pentru a nu recrea quizul la fiecare click.

Mai avem nevoie de activarea unei chei pentru partenerul guguta în backendul
PlayQuiz (PARTNER_KEYS=guguta:<cheie>). O introducem server-side și în Guguță,
fără chei în frontend sau în Git, apoi facem deploy și proba cap-la-cap.

Am păstrat fluxul tău: prima intrare cere o parolă PlayQuiz; conturile existente
cu același email se accesează prin loginul lor, fără asociere automată.
Ulterior putem discuta idempotența la crearea quizului și titlu/clasă/disciplină.

Contractul actual: docs/guguta/PLAN_INTEGRARE_PLAYQUIZ_COM.md.
