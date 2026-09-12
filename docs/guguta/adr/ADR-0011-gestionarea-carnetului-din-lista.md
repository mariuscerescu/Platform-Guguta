# ADR-0011: Gestionarea carnetului se face din listă, iar conversația există dintotdeauna

Stare: acceptat · Data: 12 septembrie 2026
Referințe: ADR-0007 (roluri de bază de date), ADR-0010 (publicare sub subcale);
`frontend-guguta/app/components/NotebookMenu.tsx`,
`frontend-guguta/app/notebook/[id]/page.tsx`, migrarea `0014_notebook_pinning`.

## Context

Lista de carnete avea, pe fiecare card și pe fiecare rând din tabel, un buton
„⋮" care nu era legat de nimic: `onClick` doar oprea propagarea către card, ca să
nu deschidă carnetul. Utilizatorul apăsa un buton care nu făcea nimic.

Acțiunile de gestionare a carnetului (redenumire, arhivare, ștergere) erau însă
în pagina carnetului, adică exact acolo unde nu te aștepți să le cauți: trebuia
să intri în carnet ca să-i schimbi titlul sau ca să-l ștergi. În plus, arhivarea
era singurul mod de a scoate un carnet din listă fără a-l pierde, iar starea
„arhivat" nu se vedea nicăieri în listă.

Trei nemulțumiri separate, aceeași zonă:

- panoul de conversație al unui carnet nou rămânea gol până când apăsai
  „Conversație nouă": `sessionId === null` ascundea complet caseta de scriere și
  afișa un îndemn;
- header-ul arăta „Intră în cont" și după autentificare (linkul ducea corect la
  carnete, doar eticheta rămânea neschimbată), iar „Despre noi" și „Resurse"
  trimiteau amândouă către pagina de start, deci erau butoane fără efect;
- Studio avea un formular de notițe manuale, în contradicție cu ideea de Studio
  ca loc unde își scriu rezultatele instrumentele.

## Decizie

1. **Meniul cardului este singurul loc pentru gestionarea carnetului.** Butonul
   „⋮" (carduri și tabel) deschide un derulant cu `Redenumește`, `Fixează sus`
   (respectiv `Anulează fixarea`) și `Șterge`. Componenta
   `NotebookMenu` oprește propagarea către card, se închide la click în afară și
   la `Escape`, iar după fiecare acțiune reîncarcă lista.
2. **Pagina carnetului păstrează doar `Partajează`.** Partajarea ține de
   conținutul carnetului deschis, nu de poziția lui în listă.
3. **Fixarea sus este o coloană în bază, nu o preferință de browser:**
   `digital_notebooks.pinned_at` (migrarea `0014`), `pinned` în contractul API
   (`PATCH /api/v1/notebooks/{id}`), iar lista ordonează `pinned_at DESC NULLS
   LAST` înaintea sortării cerute. `NULLS LAST` este obligatoriu: în PostgreSQL,
   `DESC` aduce valorile `NULL` primele.
4. **Sortarea din client respectă fixarea.** Lista își reordonează elementele în
   browser (`title` / cele mai recente), deci pinul trebuie comparat și acolo;
   altfel ordinea dată de server ar fi anulată la primul render.
5. **Conversația există dintotdeauna.** La deschiderea unui carnet fără nicio
   sesiune, pagina creează automat una, iar caseta de scriere este randată
   necondiționat (dezactivată doar în scurta clipă cât se pregătește sesiunea).
   Panoul nu are stare goală; butonul „Conversație nouă" rămâne pentru sesiuni
   suplimentare.
6. **Header-ul nu are buton de cont deloc.** Intrarea în cont stă doar pe
   pagina de start (`app/page.tsx`, butonul „Deschide Guguță"): duce la
   autentificare pentru vizitatori și direct la carnete pentru cine este deja
   autentificat. Header-ul nu afișează nici buton, nici numele utilizatorului,
   deci nu urmărește utilizatorul pe fiecare pagină. Butonul din header fusese
   cândva legat printr-o funcție transmisă din `layout.tsx`; aceea a oprit
   randarea întregii pagini (500 pe toate rutele), pentru că `layout.tsx` este
   componentă de server — orice element interactiv de acolo trebuie să rămână o
   proprietate serializabilă.
7. **Studio nu mai adaugă notițe manual.** Lista notițelor existente și
   ștergerea lor rămân; ruta `POST /api/v1/notebooks/{id}/notes` rămâne intactă
   în API, pentru revenire ulterioară.

## Consecințe

- **Arhivarea nu mai are buton în interfață**, dar rămâne completă în API
  (`PATCH {"archive": true}`) și în bază (`status`, `archived_at`). Este o
  funcție dezactivată în UI, nu eliminată: se poate readuce în meniu fără
  modificări pe server.
- **Pinul este per utilizator prin proprietate**, nu prin tabelă separată:
  carnetele aparțin unui singur proprietar, deci nu există „fixat pentru mine" —
  dacă apar carnete partajate editabile, fixarea trebuie mutată într-o tabelă de
  preferințe.
- Fixarea nu schimbă `updated_at`-ul folosit de sortarea „cele mai recente" doar
  dacă `pinned_at` este actualizat: triggerul `trg_notebooks_touch` atinge
  `updated_at` la orice `UPDATE`, deci fixarea contează ca modificare a
  carnetului.
- Un carnet nou primește o sesiune de chat imediat (un `POST` în plus la prima
  deschidere). Sesiunile goale rămân în bază până când cineva scrie în ele.
- Ștergerea unui carnet fixat, redenumirea și fixarea cer `X-Guguta-CSRF`, ca
  orice mutație; sunt acoperite de teste (`tests/guguta/test_auth_notebooks_api.py`).
- **Intrarea în cont se face doar de pe pagina de start.** Pe celelalte pagini
  (inclusiv `/app`) un vizitator nu mai are buton de autentificare; ajunge la el
  prin sigla „Guguță", care duce la pagina de start. Numele utilizatorului nu se
  afișează nicăieri în header.
- Meniul este o componentă de client folosită în două locuri (card și tabel);
  orice acțiune nouă se adaugă într-un singur fișier.
