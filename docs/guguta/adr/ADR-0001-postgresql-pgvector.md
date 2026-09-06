# ADR-0001: PostgreSQL 17 cu pgvector înlocuiește SurrealDB

Stare: acceptat · Data: 6 septembrie 2026
Decizie sursă: inițiator (C17, C18 din specificații); analiză în [ANALIZA_OSS.md](../ANALIZA_OSS.md) și [EVALUARE_OPEN_NOTEBOOK_PENTRU_GUGUTA.md](../EVALUARE_OPEN_NOTEBOOK_PENTRU_GUGUTA.md) §4.4.

## Context

Open Notebook 1.14.0 (commit `8297bb2`) persistă totul în SurrealDB 2.x prin `surrealdb`/`surreal-commands`. Licența SurrealDB 2.0 este BSL 1.1, neacceptată pentru stiva țintă Guguță. Dependența nu este doar driverul: include migrațiile `.surrealql` (1–23), interogările inline din repository-uri, ID-urile de forma `table:id` și funcțiile text/vector. Coada de joburi (`surreal-commands`) depinde și ea de SurrealDB.

Guguță cere multi-utilizator cu proprietate și autorizare pe server, tranzacții clasice, rulată pe PostgreSQL, și stocare vectorială pentru căutare semantică.

## Decizie

1. Persistența Guguță este **PostgreSQL 17** (patch suportat, imagine fixată la build), extensia **pgvector** la o versiune compatibilă fixată prin ADR și build.
2. Accesul din Python: **SQLAlchemy 2 async + psycopg 3**, migrații cu **Alembic** pornind de la zero.
3. Vectorii se stochează în tipul `vector` al pgvector; dimensiunea este validată față de `embedding_spaces` printr-un trigger; MVP folosește căutare exactă filtrată pe corpus mic, fără index aproximativ până la măsurare.
4. Dependențele `surrealdb`/`surreal-commands` rămân în `pyproject` până la L8; codul Guguță nou nu le importă. Eliminarea din buildul țintă este livrarea L8, cu cutover documentat.
5. Numele canonice ale entităților sunt cele din specificații §9; detaliile SQL se decid aici și în migrații, fără copierea schemei SurrealDB.

## Consecințe

- Migrațiile SurrealDB (1–23) nu sunt portate automat; exportul din SurrealDB este o operație separată, controlată, nu o migrare Alembic pretinsă automată.
- Interogările Guguță folosesc UUID-uri generate pe server și `timestamptz` UTC; nu se folosesc ID-uri `table:id`.
- pgvector este licențiat permisiv (PostgreSQL License); se inventariază în SBOM la build.
- Alte baze (Oracle, SQL Server) nu sunt ținte; dialectul se fixează explicit.
