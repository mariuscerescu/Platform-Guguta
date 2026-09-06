# Decizii externe încă necesare — registru

Data: 6 septembrie 2026 · Sursa: SPECIFICATII_GUGUTA.md §12, GHID_IMPLEMENTARE_LLM.md

Lista nu redeschide deciziile închise (fork Open Notebook, PostgreSQL în loc de
SurrealDB, MIT). Elementele de mai jos blochează modulele indicate și trebuie
închise de responsabili umani; un agent LLM nu le poate semna.

| ID | Decizie | Responsabil | Termen necesar | Blochează | Stare |
| --- | --- | --- | --- | --- | --- |
| D-01 | Furnizorul de identitate (OIDC) și regulile de acces pentru minori | Inițiator + responsabil instituțional | Înainte de staging public | L2 în staging, orice mediu cu elevi | DESCHISĂ |
| D-02 | Furnizori AI acceptați (chat/embedding), compatibilitate română, retenția datelor | Inițiator + responsabil tehnic | Înainte de index și chat live | L4 probă live (mock controlat permis până atunci) | DESCHISĂ |
| D-03 | Găzduire staging/pilot (host, domeniu, TLS, backup) | Inițiator + responsabil tehnic | Înainte de staging | R67–R76, L9 | DESCHISĂ |
| D-04 | Drepturile de utilizare/redistribuire pentru manualele pilot | Inițiator + editor de catalog | Înainte de popularea catalogului | L6 publicare, R88 | DESCHISĂ |
| D-05 | Clase, discipline, ediții și profesori evaluatori pentru pilot | Inițiator + editor de catalog | Înainte de pilot | L9 evaluare pedagogică, R87 | DESCHISĂ |
| D-06 | Praguri măsurabile: calitate AI, cost, latență, RPO/RTO, concurență | Echipa produs/tehnic/pedagogic | Înainte de pilot | R90, R94, L9 | DESCHISĂ |
| D-07 | Acces minorilor, informare, retenție, export, ștergere, moderare | Responsabili instituționali/juridici | Înainte de date reale | R92, R93 | DESCHISĂ |
| D-08 | Transferul sau excluderea datelor demo existente (SurrealDB/SQLite), proprietar desemnat | Inițiator | Înainte de orice cutover cu date vechi | L8 transfer, R13–R15 | DESCHISĂ |
| D-09 | Model/dimensiune embedding fixat pentru primul index | Responsabil AI/tehnic | Înainte de primul index | L3 embedding, A27 | DESCHISĂ |
| D-10 | Chei API furnizori AI (configurate în secrets manager, nu în Git) | Inițiator | Când se activează proba live | L4/L5 probe live | DESCHISĂ |

Mod de lucru: până la închiderea D-02/D-10, fluxurile AI se validează cu mock
controlat determinist; probele live rămân marcate ca blocate în rapoarte.
