# Decizii externe încă necesare — registru

Data: 6 septembrie 2026 · Sursa: SPECIFICATII_GUGUTA.md §12, GHID_IMPLEMENTARE_LLM.md

Lista nu redeschide deciziile închise (fork Open Notebook, PostgreSQL în loc de
SurrealDB, MIT). Elementele de mai jos blochează modulele indicate și trebuie
închise de responsabili umani; un agent LLM nu le poate semna.

| ID | Decizie | Responsabil | Termen necesar | Blochează | Stare |
| --- | --- | --- | --- | --- | --- |
| D-01 | Furnizorul de identitate (OIDC) și regulile de acces pentru minori | Inițiator + responsabil instituțional | Înainte de staging public | L2 în staging, orice mediu cu elevi | DESCHISĂ |
| D-02 | ~~Furnizori AI acceptați (chat/embedding), compatibilitate română, retenția datelor~~ | **ÎNCHISĂ (7 sept 2026)**: OpenRouter — Nemotron embeddings (2048d), Nemotron Rerank, MiniMax M3 chat (română). Vezi [INTEGRARE_OPENROUTER_2026-09-07.md](INTEGRARE_OPENROUTER_2026-09-07.md) | — | — | ÎNCHISĂ |
| D-09 | ~~Model/dimensiune embedding fixat pentru primul index~~ | **ÎNCHISĂ (7 sept 2026)**: `nvidia/nemotron-3-embed-1b:free`, 2048 dim; reindexare în spațiu nou pentru schimbări ulterioare | — | — | ÎNCHISĂ |
| D-10 | ~~Chei API furnizori AI~~ | **ÎNCHISĂ (7 sept 2026)**: cheie locală în `.env.guguta.local`, exclusă din Git și imaginea Docker | — | — | ÎNCHISĂ |
| D-03 | Găzduire staging/pilot (host, domeniu, TLS, backup) | Inițiator + responsabil tehnic | Înainte de staging | R67–R76, L9 | DESCHISĂ |
| D-04 | Drepturile de utilizare/redistribuire pentru manualele pilot | Inițiator + editor de catalog | Înainte de popularea catalogului | L6 publicare, R88 | DESCHISĂ |
| D-05 | Clase, discipline, ediții și profesori evaluatori pentru pilot | Inițiator + editor de catalog | Înainte de pilot | L9 evaluare pedagogică, R87 | DESCHISĂ |
| D-06 | Praguri măsurabile: calitate AI, cost, latență, RPO/RTO, concurență | Echipa produs/tehnic/pedagogic | Înainte de pilot | R90, R94, L9 | DESCHISĂ |
| D-07 | Acces minorilor, informare, retenție, export, ștergere, moderare | Responsabili instituționali/juridici | Înainte de date reale | R92, R93 | DESCHISĂ (implementare provizorie în ADR-024: acord părinte pentru I–VIII, politică și termeni ca versiune de lucru, ștergere din „Contul meu”) |
| D-08 | Transferul sau excluderea datelor demo existente (SurrealDB/SQLite), proprietar desemnat | Inițiator | Înainte de orice cutover cu date vechi | L8 transfer, R13–R15 | DESCHISĂ |


D-02, D-09 și D-10 sunt închise (7 sept 2026): OpenRouter cu Nemotron/MiniMax M3.
Probele live au trecut. Modelele :free sunt pentru dezvoltare/evaluare; pentru pilot
se alege planul plătit și pragurile de cost (D-06).
