# Divergențe între regulile upstream Open Notebook și direcția Guguță

Data: 6 septembrie 2026 · Referință: GHID_IMPLEMENTARE_LLM.md §0.2.1

Regulile din `AGENTS.md` (rădăcină și componente) rămân în vigoare pentru codul
upstream neportat. Unde ele descriu comportamente pe care Guguță le înlocuiește,
aplicăm regula Guguță și consemnăm diferența aici, ca să nu apară „corectări”
accidentale în ambele direcții.

| Zonă | Regulă upstream | Direcția Guguță | De ce |
| --- | --- | --- | --- |
| Persistență | SurrealDB + `surreal-commands`; migrații `.surrealql` cu `AsyncMigrationManager` | PostgreSQL 17 + pgvector, Alembic, migrator unic pe release (ADR-0001) | Licență BSL, multi-utilizator, tranzacții |
| Acces DB | Conexiune per apel `repo_*`, fără pool | SQLAlchemy 2 async + psycopg 3 cu pool, roluri separate, RLS (ADR-0007) | Izolare A04/A11/A23, privilegii minime |
| Migrații la pornire | API-ul rulează migrațiile automat la startup | API-ul și workerul NU migrează la pornire; job de release separat | R09/R10 din deployment readiness |
| Autentificare | Parolă comună de instanță, middleware simplu; „dev defaults” | OIDC + PKCE, sesiuni opace server-side (ADR-0003) | Elevi reali, conturi individuale |
| CORS | Deschis implicit | Origine configurată restrâns; wildcard refuzat în producție | R68, cookie-uri cu acreditări |
| Chat memory | `SqliteSaver` global în `graphs/chat.py` | Mesaje PostgreSQL, context reconstruit, fără SQLite (ADR-0005) | Memorie izolată per utilizator/carnet |
| Surse partajate | Asocierea partajează același obiect sursă | SourceAsset/MaterialVersion/NotebookSource, copii independente (ADR-0006) | C13–C15, A03/A09 |
| Excepții domeniu | `open_notebook.exceptions` tipizate → coduri HTTP | **Păstrat** pentru API-ul Guguță (rute în `/api/v1`) | Coerență, handler-e existente |
| Async-first | Totul `await` | **Păstrat**; cererile LLM nu țin tranzacții SQL | Coerență |
| Secrete în git | Interzis | **Păstrat**; plus refuz la startup a configurațiilor nesigure | R08, R73 |

Regulă practică: un PR Guguță nu modifică `open_notebook/database/migrations/*.surrealql`
sau codul surreal decât dacă portarea acelei rute o cere explicit; rutele
neportate se dezactivează, nu se „adaptează” tacit.
