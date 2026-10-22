# ADR-024: Înregistrare conversațională cu Guguță, profil școlar, consimțăminte și drepturile persoanei vizate

Data: 2026-10-21. Stare: acceptat (textele legale rămân de validat instituțional, decizia D-07).

## Context

Legislația Republicii Moldova privind protecția datelor cu caracter personal, aliniată GDPR, este în vigoare din august 2026. Platforma nu avea informare despre cookie-uri, politică de confidențialitate, termeni, consimțământ explicit la înregistrare, profil școlar (școală, clasă) sau o cale prin care elevul să-și vadă, corecteze și șteargă datele. Formularele de autentificare erau clasice, străine de restul experienței, în care Guguță este însoțitorul elevului.

## Decizie

1. **Actualizare la cererea utilizatorului, 22 octombrie 2026:** înregistrarea și autentificarea folosesc formulare clasice. Înregistrarea include prenume, nume, instituție, clasă (I–XII), e-mail, parolă și confirmarea parolei, plus acordurile existente. Câmpul instituției oferă sugestii din listele publice MEC pentru SICE, cu nume și localitate; permite și text liber. Sugestiile sunt un snapshot local (`frontend-guguta/public/schools-md.json`), actualizabil cu `python3 scripts/update_moldova_schools.py`. Listele SICE nu reprezintă registrul național complet. Browserul nu trimite căutările către MEC; lipsa listei nu blochează introducerea manuală. Nu se folosește model AI sau conversație în formular.
2. **Profil școlar**: coloanele `users.school` și `users.class_level` (cifre romane, constrângere I–XII; migrarea 0024). Clasa se normalizează din „5”, „a V-a”, „clasa a 5-a”.
3. **Consimțăminte explicite**: tabelul `user_consents(user_id, kind ∈ {privacy, terms, parent}, version)`, RLS pe utilizator. Înregistrarea cere `privacy_accepted=true`; codul cere provizoriu și `parent_consent=true` pentru clasele I–VIII. Această regulă pe clase nu este verificarea prevăzută de art. 8 din Legea nr. 195/2024: pragul pentru servicii online bazate pe consimțământ este 14 ani, iar formularul nu verifică separat identitatea reprezentantului legal. Politica și termenii rămân proiecte de lucru până la validarea instituțională (D-07). Versiunea politicii (`PRIVACY_POLICY_VERSION`) este expusă în `GET /api/v1/auth/config` și în `/auth/me` (`consents`); aplicația nu cere încă automat reafirmarea acordului după schimbarea versiunii.
4. **Drepturile persoanei vizate**: `GET /api/v1/auth/me` întoarce e-mail, școală, clasă și acordurile (acces); `PATCH /api/v1/auth/me` corectează numele, școala, clasa (rectificare); `DELETE /api/v1/auth/me` șterge carnetele proprii (cu fișierele lor, prin mecanismele existente), identitățile, credențialele, sesiunile și consimțămintele și anonimizează rândul din `users` (`status='deleted'`, fără nume, e-mail, școală, clasă), pentru că audit, catalog și partajări îl referă cu RESTRICT. Pagina `/cont` („Contul meu”) expune toate acestea.
5. **Cookie-uri**: platforma folosește doar cookie-uri strict necesare (`guguta_session`, `guguta_oidc_state`) și stocare locală pentru preferințe; informarea (`CookieNotice`) se afișează o dată, fără mecanism de refuz, pentru că nu există cookie-uri de urmărire. Paginile `/confidentialitate` și `/termeni` descriu datele, scopurile, temeiurile, împuterniciții (OpenRouter, voce, PlayQuiz la acțiune explicită), retenția și drepturile; subsolul leagă spre ele.

## Consecințe

- Conturile create înainte au `school`/`class_level` NULL și fără acorduri; pagina „Contul meu” le poate completa. O cerere ulterioară de acord retroactiv la intrare se face când versiunea politicii se schimbă.
- Pragul legal și verificarea autorizării reprezentantului legal pentru copiii sub 14 ani trebuie finalizate înainte de date reale; D-07 rămâne deschisă.
- Exportul datelor (portabilitate) rămâne la cerere, prin e-mail; nu există încă un endpoint de export.
