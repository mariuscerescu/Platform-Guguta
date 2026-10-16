# ADR-021: Integrarea PlayQuiz prin sesiunea Guguță

Data: 2026-10-08. Stare: acceptat.

PlayQuiz este publicat sub `/edu-platform/playquiz`, iar API-ul Java sub `/edu-platform/playquiz-api`. Folosește sesiunea HttpOnly `guguta_session`, validată de API-ul Guguță la fiecare cerere autentificată. Autentificarea JWT, înregistrarea și autentificarea socială independente sunt dezactivate în modul integrat.

Profilul este sincronizat în Oracle folosind UUID-ul Guguță unic. Parolele nu se copiază. Rolurile administrative nu sunt preluate automat. Baza PostgreSQL și RLS rămân autoritatea pentru carnete, quizuri și încercări. Catalogul arată numai quizuri gata, create de utilizatorul autentificat, din carnete active.

PlayQuiz afișează momentan numai quizuri alcătuite integral din întrebări grilă (multiple_choice și multiple_select) și transmite răspunsurile către API-ul existent Guguță. Evaluarea și rezultatele rămân în carnet, evitând copii divergente ale răspunsurilor corecte și ale evaluatorului semantic. Proxy-ul Java acceptă numai rute explicite cu UUID-uri, folosește un URL intern configurat și păstrează CSRF pe ambele API-uri.

Oracle este separat, cu volum persistent și credențiale generate. API-ul și interfața sunt publicate numai pe localhost, prin nginx. Serviciile GPU și worker-ul nu se modifică.

Actualizare (2026-10-08): quizurile sunt afișate în catalogul nativ `/quiz/categorized`, fără listă sau categorie Guguță. Playerul folosește `/quiz/categorized/{quiz}?notebook={notebook}`; adresele vechi redirecționează. Clasificarea pe clase și discipline rămâne pentru o etapă ulterioară. Catalogul filtrează tipurile întrebărilor efective înainte de paginare, iar API-ul Java verifică aceeași restricție la citire, începere, răspuns și rezultate. Quizurile cu completări sau răspunsuri libere rămân disponibile în Guguță.
