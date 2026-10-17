# Plan de lucru: sesiuni cloud Claude Code (sau Codex local)

Stare: 17 octombrie 2026. Fișier de lucru pentru valorificarea creditului de
sesiuni cloud (expiră 5 noiembrie 2026). Fiecare sarcină de mai jos este
independentă, are un prompt gata de folosit și criterii de acceptare. Sarcinile
pot fi date și unui agent local (Codex) în același repo; promptul este același.

Repo: `https://github.com/mariuscerescu/Platform-Guguta` (public). Branch de
lucru: `dev`. `main` se avansează doar fast-forward din `dev` după verificare.
Documentul de referință pentru sarcinile 2–5: [IDEI_UI_ADAPTIV.md](IDEI_UI_ADAPTIV.md).

---

## A. Pași manuali, o singură dată (Tudor)

1. **GitHub CLI** este instalat în `~/.local/bin/gh`. Autentificare interactivă:
   ```
   gh auth login
   ```
   Alege GitHub.com, HTTPS, autentificare prin browser, contul `bumbutudor`.
2. **Conectează GitHub la Claude Code**: în Claude Code rulează `/web-setup`.
   Alternativ, în browser: <https://claude.ai/code/onboarding?step=alt-auth>.
3. **Aplicația Claude GitHub pe repo**: repo-ul este al lui Marius, deci
   instalarea aplicației pe `mariuscerescu/Platform-Guguta` o face Marius
   (GitHub → Settings → Integrations → GitHub Apps → Claude). Dacă nu se poate,
   `gh repo fork mariuscerescu/Platform-Guguta --clone=false` și lucrezi pe fork.
4. **Pornirea unei sesiuni**: din `/home/jupyter-tudor/integrations/playquiz/Guguta-Platform`
   ```
   claude --cloud "<promptul sarcinii, copiat de mai jos>"
   ```
   sau din <https://claude.ai/code>, repo + branch `dev` + promptul. Rezultatul
   vine ca PR către `dev`; local se continuă cu `claude --teleport`.

Limite ale sesiunilor cloud: nu văd serverul (Docker, nginx, GPU, PostgreSQL de
producție). Pot rula `uv run pytest`, `ruff`, `mypy`, `npm run build`,
`npx playwright test` și pot porni un PostgreSQL de test dacă mediul permite.

---

## B. Preambul comun pentru toate prompturile

Lipește acest bloc la începutul fiecărui prompt:

```
Lucrezi în repo-ul Guguță (fork Open Notebook; frontend-guguta/ Next.js 15,
api/ FastAPI, open_notebook/ domeniu, alembic/ migrări, tests/guguta/).
Reguli: citește întâi AGENTS.md, docs/guguta/SPECIFICATII_GUGUTA.md și
docs/guguta/IDEI_UI_ADAPTIV.md. Interfața este în română (ro-MD). Nu atinge
frontend/ (interfața upstream) și nu schimba schema fără migrare Alembic nouă.
Orice decizie structurală se consemnează ca ADR nou în
docs/7-DEVELOPMENT/decisions/ (următorul număr liber). Rulează ruff, mypy și
testele relevante înainte de a deschide PR. Lucrează pe o ramură din `dev` și
deschide PR către `dev`, cu descriere în română.
```

---

## C. Sarcini

### 1. Deploy la zi (local, nu cloud; Codex sau manual pe server)

Serverul raportează la `/edu-platform/guguta-api/versionz` commit-ul `65ac381`
(7 octombrie). GitHub `main` este cu 8 commit-uri înainte (teme, însoțitor cu
voce, integrarea PlayQuiz, documentație). Sarcina: actualizează checkout-ul de
build de pe server la `origin/main` și reconstruiește stack-ul `guguta-edu`
(`deploy/edu-platform/`), fără să atingi `.env`, volumele sau stack-ul PlayQuiz.
Verificare: `/versionz` arată noul commit, autentificarea și chatul funcționează,
linkul PlayQuiz din header duce la `/edu-platform/playquiz/guguta`.

### 2. Profilul de interfață „primar” (cloud)

```
Implementează profilul de interfață pentru clasele primare, conform
docs/guguta/IDEI_UI_ADAPTIV.md §1, faza de prototip.

Backend:
- câmp `ui_profile` (enum: primar | gimnazial | liceal, implicit gimnazial) pe
  utilizator și pe șablonul din catalog; migrare Alembic nouă; expus în
  /api/v1/auth/me și în răspunsul carnetului (profilul șablonului are prioritate,
  apoi al utilizatorului); endpoint PATCH pentru schimbarea profilului de către
  utilizator; teste în tests/guguta/.
Frontend (frontend-guguta/):
- atribut `data-profile` pe <html>, setat din /auth/me și din carnet;
- design tokens pe profil în app/theme.css (text ≥ 18px, ținte ≥ 44px, spațieri
  mai mari pentru `primar`), ortogonal cu tema deschisă/întunecată;
- pagina carnetului: layout pe o coloană pentru `primar` (conversația în
  centru, materialele și Studio în două butoane mari cu pictograme care
  deschid panouri peste pagină); celelalte profiluri rămân cu trei panouri;
- comutator de profil în meniul utilizatorului; schimbarea nu reîncarcă pagina.
Acceptare: niciun text sub 16px în profilul primar; flux Playwright nou în
frontend-guguta/e2e pentru profilul primar; `npm run build` curat; ADR nou.
```

### 3. Registrul de limbaj pentru profilul primar (cloud, mică)

```
Adaugă un dicționar ro-MD cu două registre pentru etichetele interfeței
(frontend-guguta/lib/i18n-profile.ts): registrul „primar” folosește cuvinte
simple („Materialele mele” în loc de „Surse”, „Hai să exersăm” în loc de
„Quiz”, „Ascultă” în loc de „Prezentare audio”). Înlocuiește etichetele
hardcodate din componentele carnetului, Studio și header cu apeluri la
dicționar, selectate după `data-profile`. Fără schimbări vizuale pentru
profilurile gimnazial și liceal. Acceptare: lista completă a etichetelor
înlocuite în descrierea PR; testele E2E existente trec.
```

### 4. Tonul tutorelui pe profil (cloud, mică)

```
Promptul tutorelui (open_notebook/..., vezi ADR-017 și PDR-003) primește
profilul de interfață al carnetului. Pentru `primar`: propoziții scurte, un
singur pas pe mesaj, întrebare de verificare la final, laudă concretă, fără
termeni abstracți; pentru `liceal`: ton mai dens, cu referințe la pagini.
Nu schimba regulile de citare sau de ne-dezvăluire a soluției. Adaugă teste
care verifică că promptul conține instrucțiunile pe profil și un test de
regresie pe formatul citărilor. ADR nou sau amendament la ADR-017.
```

### 5. Scena vie, faza 1 (cloud, mare)

```
Implementează faza 1 din docs/guguta/IDEI_UI_ADAPTIV.md §2.

Backend:
- schemă pydantic strictă pentru directivele de scenă: `objects`
  (tip ∈ {apple, ball, book, coin, star}, culoare, număr ≤ 20, grupuri cu
  etichetă), `number_line` (min, max, marcaje, salturi), `board_text` (≤ 80
  caractere, evidențieri), `clear`; fiecare directivă are `step` (int);
- modelul tutorelui emite directivele într-un bloc structurat separat de text
  (instrument/tool call sau bloc JSON delimitat); API-ul le validează, le
  elimină dacă sunt invalide (fără a opri răspunsul) și le trimite pe fluxul
  SSE existent al chatului ca eveniment `scene`, separat de `token`;
- buget: maximum 20 obiecte și 6 directive pe mesaj; regula din prompt: nu pune
  pe tablă rezultatul final înainte ca elevul să încerce;
- persistare: coloană `scene` JSONB pe mesajul de chat (migrare Alembic), ca
  scena să se reconstruiască la redeschidere;
- teste: validare schemă, filtrare, fluxul SSE cu eveniment `scene`.
Frontend (frontend-guguta/app/components/SceneBoard.tsx + scene-board.css):
- randare SVG a primitivelor, animație simplă la apariție, derulare pe pași
  (înainte/înapoi), buton de oprire a scenei; echivalent text pentru fiecare
  scenă (aria-live);
- montare în pagina carnetului: în zona liberă din profilul primar, ca panou
  colapsabil în celelalte profiluri;
- fără interacțiune drag-and-drop în faza 1.
Acceptare: pe un carnet „Matematică, clasa a II-a”, întrebarea „Am 3 mere verzi
și 3 mere roșii, câte mere am?” produce o scenă cu două grupuri de mere înainte
de rezultat; teste backend verzi; flux Playwright nou; ADR nou cu vocabularul
versiunii 1.
```

### 6. Igienă: PlayQuiz din catalog numai când e configurat (cloud, mică)

```
Linkurile către PlayQuiz din header și din dialogul de quiz
(frontend-guguta/app/components/SiteHeader.tsx, app/notebook/[id]/page.tsx)
apar necondiționat. Adaugă o capabilitate `playquiz` în răspunsul
/api/v1/auth/me (activă când variabila GUGUTA_PLAYQUIZ_BASE_PATH este setată) și
afișează linkurile doar atunci. Documentează variabila în .env.guguta.example
și în deploy/edu-platform/.env.example. Teste pentru ambele stări.
```

---

## D. Ordine recomandată

Paralel, în sesiuni separate: 2, 3, 4, 6. Sarcina 5 după ce PR-ul de la 2 este
în `dev` (are nevoie de `data-profile`). Sarcina 1 se face local, pe server,
oricând după ce `dev` conține ce vrem să fie live.
