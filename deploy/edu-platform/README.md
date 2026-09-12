# Platforma Guguță — instalare pe server

Publicare: **https://tineri.math.md/edu-platform**
Rulează integral în Docker, pe același server cu aplicațiile `ttsdatasetbuilder`
(`/datasetBuilder/` și `/voiceRecording/`), fără să le atingă: stack-ul are
numele de proiect `guguta-edu`, volume proprii și un singur port publicat, pe
loopback.

---

## 1. Cum stă aplicația pe server

```
browser
  │  https://tineri.math.md/edu-platform/...        (TLS, certificatul existent)
  ▼
nginx gazdă  ──► 127.0.0.1:8300   (doar loopback; adaugi un bloc `location`)
  │
  ▼
container frontend  (Next.js, construit cu basePath=/edu-platform, port 3001)
  │  /edu-platform/guguta-api/*  → proxy same-origin (next.config.ts)
  ▼
container api  (FastAPI, port 5055, /api/v1 + /healthz)
  ├──► container db    (PostgreSQL 17 + pgvector, port 5432)
  └──► container worker (procesează materialele: text, embeddings)
```

De ce trece totul prin frontend: browserul vorbește cu o singură origine, deci
cookie-ul de sesiune (`SameSite=Lax`) funcționează fără CORS și fără expuneri
suplimentare. **API-ul și baza de date nu sunt publicate pe gazdă deloc** — nu
au port în afara rețelei Docker.

| Serviciu | Port în container | Port pe gazdă | Rol |
|---|---|---|---|
| `frontend` | 3001 | `127.0.0.1:8300` | UI, singurul punct public |
| `api` | 5055 | — | logica aplicației |
| `worker` | — | — | procesare asincronă |
| `db` | 5432 | — | date + vectori |

---

## 2. Ce conține acest director

| Fișier | Rol |
|---|---|
| `docker-compose.yml` | stack-ul de producție |
| `.env` | **configurarea reală, cu secrete.** Nu se urcă în Git (`.gitignore` îl exclude) |
| `.env.example` | șablon fără secrete, pentru referință |
| `docker-compose.preview.yml` | suprascrieri pentru test local (http pe localhost) |
| `nginx-edu-platform.conf` | blocul `location` pe care îl adaugi în nginx-ul gazdă |
| `gen-env.py` | regenerează `.env` cu secrete noi, preluând cheia API existentă |

---

## 3. Cerințe pe server

- Docker + Docker Compose v2 (`docker compose version`)
- portul **8300** liber pe loopback (`ss -ltnp | grep 8300`)
- nginx-ul care servește deja `tineri.math.md`
- acces la internet (descărcarea imaginilor de bază + apelurile către OpenRouter)
- ~2 GB RAM liberi și ~3 GB disc pentru imagini, plus spațiu pentru materiale

---

## 4. Instalare, pas cu pas

### 4.1 Copiază proiectul pe server

Proiectul **nu este încă în Git**, deci se copiază directorul. Ai nevoie de
întregul `open-notebook/`, mai puțin `node_modules`, `.next`, `.venv` (se
reconstruiesc în containere; `.dockerignore` le și exclude din context).

Din mașina locală (ajustează utilizatorul și calea):

```bash
scp -r "open-notebook" utilizator@tineri.math.md:/opt/guguta/
```

Apoi, pe server:

```bash
cd /opt/guguta/open-notebook/deploy/edu-platform
chmod 600 .env          # fișierul cu secrete
```

### 4.2 Configurează `.env`

Fișierul e deja completat cu secrete generate aleator și cu cheia OpenRouter
existentă. Verifică doar:

| Variabilă | Valoare așteptată | De ce contează |
|---|---|---|
| `GUGUTA_ENVIRONMENT` | `production` | refuză secretele de dev, http și furnizorii simulați |
| `GUGUTA_BASE_PATH` | `/edu-platform` | **se citește la BUILD**; schimbarea lui cere rebuild |
| `GUGUTA_HTTP_PORT` | `8300` | portul către care trimite nginx-ul gazdă |
| `GUGUTA_PUBLIC_ORIGIN` | `https://tineri.math.md` | origine fără cale; dă flag-ul `Secure` pe cookie |
| `GUGUTA_CORS_ORIGINS` | `["https://tineri.math.md"]` | altfel API-ul răspunde **403** la orice acțiune cu cookie |
| `GUGUTA_OPENROUTER_API_KEY` | cheia ta | fără ea API-ul refuză pornirea |
| `GUGUTA_OPENROUTER_CHAT_MODEL` | modelul dorit | modelul de chat |
| `GUGUTA_EMBEDDING_DIMENSION` | `2048` | obligatoriu 2048 pentru Nemotron, altfel API-ul refuză pornirea |

Dacă vrei alte secrete: rulează `python3 gen-env.py` pe mașina de dezvoltare
(scriptul preia cheia OpenRouter din `.env.guguta.local` și rescrie `.env`), apoi
copiază fișierul pe server. Pentru un singur secret nou, oriunde:
`openssl rand -base64 36`.

> `GUGUTA_PUBLIC_ORIGIN` **nu** conține `/edu-platform`. Antetul `Origin` trimis
> de browser este doar schemă + gazdă + port; cu calea inclusă, verificarea
> eșuează și aplicația pare „stricată" la prima acțiune.

### 4.3 Pornește stack-ul

```bash
docker compose up -d --build
```

La prima rulare: descarcă imaginile de bază, construiește cele trei imagini ale
aplicației (migrator, api/worker, frontend — câteva minute), pornește baza de
date, aplică migrările și abia apoi pornește API-ul, worker-ul și frontend-ul.

```bash
docker compose ps -a       # db/api/worker/frontend = running, migrator = exited (0)
```

`migrator` care apare ca `exited (0)` este corect: rulează o dată, aplică
migrările și se oprește (ADR-0007 — API-ul și worker-ul nu migrează niciodată).

### 4.4 Verifică înainte de a atinge nginx-ul

```bash
curl -s http://127.0.0.1:8300/edu-platform/guguta-api/healthz
# {"status":"ok"}

curl -s http://127.0.0.1:8300/edu-platform/guguta-api/readyz
# {"status":"ok","schema":"0013"}       <- schema din baza de date

curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8300/edu-platform
# 200
```

Dacă toate trei răspund, aplicația e sănătoasă și izolată corect. Abia acum are
sens să expui prin nginx.

### 4.5 Publică prin nginx

Adaugă blocul `location /edu-platform { ... }` din
`nginx-edu-platform.conf` în blocul `server` care servește deja
`tineri.math.md`, apoi:

```bash
nginx -t && systemctl reload nginx
```

Două detalii care, dacă lipsesc, produc exact două simptome clasice:

- `proxy_pass http://127.0.0.1:8300;` — **fără** `/` la final. Cu `/`, nginx taie
  prefixul `/edu-platform`, iar aplicația răspunde 404 (ea așteaptă calea întreagă).
- `client_max_body_size 32m;` — implicit nginx taie la **1 MiB**, deci orice
  material urcat dă `413 Request Entity Too Large`.

Blocul din acest director a fost probat cu un nginx real (`nginx:1.27-alpine`)
pus în fața stack-ului containerizat, cu fișierul livrat inclus nemodificat:

| Probă | Rezultat |
|---|---|
| rutele aplicației prin nginx | 200 (`/edu-platform`, `/app`, `/login`) |
| API prin prefix | 200 (`healthz`, `readyz` cu schema `0013`) |
| alte căi pe același domeniu | 404 (aplicațiile existente rămân neatinse) |
| corp de 2 MiB | trece mai departe (cu limita implicită ar fi fost `413`) |
| corp de 40 MiB | `413`, deci limita chiar se aplică |
| origine nelistată | `403 origin_rejected` — deci `GUGUTA_CORS_ORIGINS` contează |
| răspunsul de chat | sosește în flux (textul crește), nu dintr-o dată la final |

Fluxul complet a trecut prin nginx: înregistrare din browser, carnet creat,
material urcat și procesat de worker, răspuns real al modelului afișat în
interfață, consolă curată.

Verificare finală în browser: `https://tineri.math.md/edu-platform` → pagina
publică, apoi „Creează cont" pentru primul utilizator.

---

## 5. Test local, înainte de a urca pe server

Aceleași imagini, aceeași aplicație, doar originile devin `localhost` (în
producție configurația cere obligatoriu `https`):

```bash
docker compose -f docker-compose.yml -f docker-compose.preview.yml up -d --build
# http://localhost:8300/edu-platform
docker compose -f docker-compose.yml -f docker-compose.preview.yml down
```

Modelele, cheia și restul setărilor rămân cele de producție, deci testul
exercită drumul real: încărcare de material, procesare în worker, chat cu
referințe.

---

## 6. Operare curentă

```bash
docker compose logs -f api worker       # urmărește API-ul și procesarea
docker compose restart api worker       # repornire simplă
docker compose up -d --build            # după modificări de cod sau de .env
docker compose down                     # oprește (volumele rămân)
```

Ce cere rebuild și ce nu:

| Schimbare | Comandă |
|---|---|
| cod (frontend, api, worker) | `docker compose up -d --build` |
| modele LLM, cheie, limite | `docker compose up -d` (doar recreează containerele) |
| `GUGUTA_BASE_PATH` | rebuild obligatoriu: valoarea intră în bundle-ul de client |
| `GUGUTA_CORS_ORIGINS`, `GUGUTA_PUBLIC_ORIGIN` | `docker compose up -d` |

**Backup**

```bash
docker compose exec -T db pg_dump -U guguta_migrator guguta > guguta-$(date +%F).sql
```

Materialele urcate stau în volumul `guguta-edu_guguta_storage`:

```bash
docker run --rm -v guguta-edu_guguta_storage:/data -v "$PWD":/backup alpine \
  tar czf /backup/guguta-storage-$(date +%F).tar.gz -C /data .
```

**Restaurare**: `docker compose up -d db`, apoi
`docker compose exec -T db psql -U guguta_migrator -d guguta < backup.sql`.

**Reset complet** (șterge datele!): `docker compose down -v`.

---

## 7. Depanare

| Simptom | Cauză | Fix |
|---|---|---|
| 404 pe `/edu-platform` | `proxy_pass` scris cu `/` la final, sau frontend construit fără `basePath` | scoate `/`-ul; rebuild cu `GUGUTA_BASE_PATH=/edu-platform` |
| Pagina se încarcă fără stiluri, linkurile duc la rădăcina domeniului | build fără `basePath` | `docker compose build --no-cache frontend` |
| `403 origin_rejected` la încărcare/chat | `GUGUTA_CORS_ORIGINS` nu conține exact `https://tineri.math.md` | corectează `.env`, `docker compose up -d api worker` |
| `413` la urcarea unui material | `client_max_body_size` implicit (1 MiB) | adaugă `client_max_body_size 32m;` în `location` |
| Răspunsul de chat apare dintr-o dată, la final | nginx ține răspunsul în buffer | `proxy_buffering off;` în `location` |
| API-ul nu pornește și scrie `unsafe configuration: ...` | configurație de producție incompletă (secret scurt, origine http, provider `mock`) | mesajul spune exact ce lipsește |
| `GUGUTA_OPENROUTER_API_KEY is required` | cheia lipsește din `.env` | completează și `docker compose up -d` |
| `Nemotron embeddings require ... 2048` | dimensiune greșită | `GUGUTA_EMBEDDING_DIMENSION=2048` |
| Upload-ul rămâne „în procesare" | worker-ul nu rulează | `docker compose logs worker`, apoi `docker compose up -d worker` |
| `502` la autentificare | API-ul nu răspunde | `docker compose ps`, `docker compose logs api` |

---

## 8. Securitate

- `.env` conține secrete reale: `chmod 600`, fără copii în Git, fără paste-uri.
- `.dockerignore` exclude `.env` din contextul de build — secretele nu ajung în
  straturile imaginilor.
- Portul 8300 e publicat **doar pe `127.0.0.1`**: nu îl deschide în firewall și
  nu îl adăuga la vreun `proxy_pass` public. Tot traficul intră prin nginx, cu TLS.
- `GUGUTA_CREDENTIAL_ENCRYPTION_KEYS` (`k1`): **nu îl schimba** după ce există
  credențiale salvate — devin indescifrabile. Pentru rotație, adaugă `k2` și
  schimbă `GUGUTA_CREDENTIAL_KEY_PRIMARY_ID`.
- Parolele rolurilor PostgreSQL se aplică la **prima** pornire cu volum gol.
  Ulterior se schimbă doar manual (`ALTER ROLE guguta_api WITH PASSWORD ...` în
  containerul `db`), altfel `.env` și baza de date ajung să nu se mai potrivească.
