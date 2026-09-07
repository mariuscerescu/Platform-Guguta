# Integrare OpenRouter — Guguță

Data: 7 septembrie 2026. Bază: `14b51a5`, plus modificările locale de integrare.

## Modele și rezultate reale

| Rol | Model exact | Verificare |
|---|---|---|
| Embeddings | `nvidia/nemotron-3-embed-1b:free` | HTTP 200; vectori de **2048** dimensiuni |
| Reranker | `nvidia/llama-nemotron-rerank-vl-1b-v2:free` | HTTP 200; fragmentul despre fotosinteză înaintea celui despre triunghiuri |
| Chat | `minimax/minimax-m3:free` | HTTP 200; răspuns în română cu citare validată |

Integrarea folosește endpointurile OpenRouter `embeddings`, `rerank` și `chat/completions`, toate sub `https://openrouter.ai/api/v1/`. Nu există fallback automat la alte modele sau la variante plătite. Un model indisponibil produce eroare controlată.

Documentație consultată: [embeddings](https://openrouter.ai/docs/api/reference/embeddings), [rerank](https://openrouter.ai/docs/api/api-reference/rerank/submit-a-rerank-request), [RAG](https://openrouter.ai/docs/cookbook/evaluate-and-optimize/rag).

## Ce s-a implementat

- Adaptoare async OpenRouter, fără dependență nouă de SDK; se folosește `httpx` deja prezent în imagine.
- Cheie de tip `SecretStr`; fișier local `.env.guguta.local`, ignorat de Git și exclus din contextul Docker. Valorile secrete nu sunt întoarse prin API sau introduse în mesaje de eroare.
- Timeout pe apel, retry limitat pentru throttling/indisponibilitate și respectarea unui `Retry-After` scurt. Redirecturile nu sunt urmate cu cheia de autentificare.
- Embeddings în loturi de maximum 16 texte implicit; verificarea numărului, ordinii, dimensiunii și valorilor finite, inclusiv respingerea vectorilor nuli.
- Căutare autorizată pe carnet, combinarea candidaților text/vector, apoi reranking al candidaților. Rerankerul primește numai fragmentele selectate și autorizate. Obiectele locale și citările originale sunt păstrate; textul returnat de reranker nu înlocuiește sursele.
- Apelurile externe de embeddings/reranking/chat rulează în afara tranzacțiilor DB. Chatul verifică din nou revizia carnetului după retrieval și înaintea salvării.
- Prompt educațional în română, cu materialele delimitate ca date neîncredere; răspuns JSON și verificarea indicilor/citărilor înainte de publicare. Răspunsurile trunchiate sau invalide sunt respinse. La una dintre probele preliminare, validatorul a respins un răspuns; probele live finale au trecut. Formatul de ieșire al unui LLM nu este garantat la fiecare apel.
- Tokenurile și costul raportate pentru generarea chatului sunt persistate, împreună cu modelul și versiunea `guguta-openrouter-1`. Nu reprezintă încă contabilizarea completă a costului embeddings/reranking; contoarele existente fără date de usage păstrează comportamentul de estimare al MVP-ului.
- Script de reindexare într-un spațiu nou: indexul anterior rămâne activ la eșec; reluarea nu dublează embeddings; activarea are loc numai după verificarea completitudinii.
- Configurație Compose explicită pentru OpenRouter; configurația de bază și testele automate rămân fără apeluri externe implicite.

## Dovezi de testare

1. `tests/guguta/test_openrouter.py`: **15 teste** de contract, fără rețea, pentru batch, ordonare, output invalid, citări, retry, timeout și secrete.
2. `tests/guguta/test_openrouter_pipeline.py`: pipeline API/worker/PostgreSQL cu provider simulat și pipeline live cu toate cele trei modele reale. Verifică și lipsa unei conexiuni SQL reținute în timpul apelurilor AI. Test suplimentar pentru eșec/reluare/reexecutare reindexare.
3. [Rezultat live API/worker în procesul de test](openrouter-live-results.json): procesare a materialelor, selecție, retrieval/reranking, chat, citări și usage persistat.
4. [Rezultat Docker separat](openrouter-docker-results.json): API și worker în containere distincte, PostgreSQL izolat, toate apelurile AI reale; `/readyz` raportează schema `0011`.
5. [Rezultate regresie](openrouter-regression-results.xml): **80 passed, 1 skipped**, 25,80 secunde. Testul live este sărit implicit și a fost executat separat cu opt-in.
6. Build Docker reușit; `pip check` în imagine fără conflicte. Ruff și Mypy verificate pe codul schimbat și testele noi.

Două teste existente nu sunt incluse în rularea de regresie: `test_a22_restore.py` și `test_oidc_http_f01.py`, deoarece depind de containerul/DSN-ul fix al mediului existent. Nu s-a rerulat un audit complet de securitate sau un test de încărcare. Integrarea AI nu echivalează cu închiderea întregului audit backend.

## Activare în mediul local

Fișierul `.env.guguta.local` a fost creat local cu cheia furnizată și cele trei modele. El nu este citit automat de configurația de bază, pentru a nu transforma testele obișnuite în apeluri externe.

Pentru o bază **nouă**, se folosește override-ul explicit:

```powershell
docker compose -f docker-compose.guguta.yml -f docker-compose.guguta.openrouter.yml up -d --build api worker
```

Pentru o bază **existentă cu embeddings hash**, reindexarea trebuie făcută înainte de utilizarea noilor modele. Procedură de mentenanță:

1. Backup DB + fișiere; confirmă că materialele pot fi trimise furnizorului extern ales.
2. Oprește scrierile API și workerul pentru baza țintă:

```powershell
docker compose -f docker-compose.guguta.yml stop api worker
```

3. Configurează DSN-ul de migrator corect în `.env.guguta` (fișier local, fără secrete în Git). Scriptul citește `.env.guguta` și `.env.guguta.local`; variabilele procesului au prioritate.
4. Din rădăcina repository-ului:

```powershell
$env:PYTHONPATH='.'
.venv\Scripts\python.exe scripts/guguta_reindex_openrouter.py --maintenance
```

5. Dacă reindexarea eșuează, spațiul vechi rămâne activ; rezolvă cauza și reia aceeași comandă. Dacă a reușit, pornește API și worker cu override-ul OpenRouter de mai sus.

Reindexarea nu șterge manualele, fragmentele sau vectorii vechi. O schimbare ulterioară de model/revizie necesită un spațiu nou; nu edita metadatele vechi pentru a pretinde compatibilitate. Scriptul este destinat mentenanței, nu reindexării online cu scrieri concurente.

**Nu au fost reindexate și nu au fost trimise la OpenRouter materialele deja existente în baza utilizatorului.** Validarea s-a făcut exclusiv cu date sintetice într-o bază separată. Pornirea Docker Desktop a necesitat păstrarea unor directoare de socketuri defecte sub nume de backup; volumele și configurațiile aplicației nu au fost resetate.

Backupuri ale socketurilor, sub `%LOCALAPPDATA%`: `Docker/run.openrouter-backup-20260907`, `Docker/run.openrouter-backup-20260907-2`, `docker-secrets-engine.openrouter-backup-20260907-2`. Acestea nu sunt backupuri ale datelor platformei.

## Reproducerea testelor

Testele DB recreează `guguta_test` și setează parolele rolurilor. Folosește exclusiv un server disposable, nu serverul unei aplicații reale.

```powershell
$env:GUGUTA_TEST_DATABASE_URL='<DSN migrator al serverului disposable>'
.venv\Scripts\python.exe -m pytest tests/guguta/test_openrouter.py tests/guguta/test_openrouter_pipeline.py -q
```

Pentru proba externă explicită:

```powershell
$env:GUGUTA_LIVE_OPENROUTER='1'
.venv\Scripts\python.exe -m pytest tests/guguta/test_openrouter_pipeline.py -k live -q
Remove-Item Env:GUGUTA_LIVE_OPENROUTER
```

`scripts/guguta_openrouter_smoke.py` țintește numai API-ul de test de pe portul 55435. Presupune că API, worker și PostgreSQL sunt deja pornite cu configurația OpenRouter și autentificare de dezvoltare. Nu este script de deployment.

## Limite importante pentru următoarea etapă

- Endpointurile gratuite NVIDIA cer să nu fie trimise date personale sau confidențiale. Profilul curent este pentru dezvoltare/evaluare cu materiale adecvate; vezi [pagina modelului](https://openrouter.ai/nvidia/llama-nemotron-rerank-vl-1b-v2:free).
- Disponibilitatea și limitele variantelor `:free` se pot schimba. Retry-ul limitat nu oferă SLA și nu ascunde lipsa capacității.
- Rerankerul este folosit acum pe **text**. Capacitățile sale vizuale nu adaugă automat OCR sau înțelegerea imaginilor în pipeline-ul actual.
- Citările sunt validate structural: indică fragmente furnizate modelului. Aceasta nu dovedește automat că fiecare afirmație este susținută semantic de sursă.
- Este necesară o evaluare mai amplă pe manuale românești, întrebări fără răspuns, instrucțiuni ostile în documente și concurență/costuri înainte de lansarea cu elevi reali.
