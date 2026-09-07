# ADR-0008 — Furnizori AI inițiali prin OpenRouter

Data: 7 septembrie 2026. Status: acceptat prin instrucțiunea explicită a utilizatorului; integrare verificată cu date sintetice.

## Decizie

Folosim OpenRouter pentru cele trei roluri: `nvidia/nemotron-3-embed-1b:free` (embeddings, 2048 dimensiuni), `nvidia/llama-nemotron-rerank-vl-1b-v2:free` (reranking text) și `minimax/minimax-m3:free` (generare în română).

Implementarea este în adaptoarele Guguță, fără importarea stivei SurrealDB/LangChain upstream. Transportul HTTP este async, iar apelurile AI se fac după eliberarea conexiunilor DB. Factory-urile păstrează mock-urile pentru teste și dezvoltare fără rețea. Cheia se injectează local; nu este publicată în Git, API sau imaginea Docker.

Nu se schimbă tacit modelul sau varianta gratuită. Răspunsurile eronate produc eșec controlat. Rerankingul operează exclusiv pe candidații autorizați din Carnetul digital. Citările sunt validate față de fragmentele originale.

## Consecințe

Vectorii hash nu sunt compatibili cu noul model. Trecerea unei baze existente necesită reindexare într-un spațiu separat, cu activare după completitudine și păstrarea vechiului index la eșec.

Acest profil gratuit nu aprobă prelucrarea datelor personale ale elevilor și nu oferă SLA. Evaluarea semantică în română, limitele de consum și acceptanța de producție rămân activități separate. Nu s-a implementat OCR sau reranking vizual prin simpla alegere a unui model multimodal.

Instrucțiuni, rezultate și limite: [raportul integrării](../INTEGRARE_OPENROUTER_2026-09-07.md).
