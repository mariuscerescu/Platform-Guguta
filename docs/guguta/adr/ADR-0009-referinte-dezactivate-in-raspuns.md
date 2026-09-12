# ADR-0009: Referințele din răspuns — afișare dezactivată, funcționalitate păstrată

Stare: acceptat · Data: 11 septembrie 2026
Referințe: SPECIFICATII_GUGUTA.md §5 (A12, A13), §9; checklist L5 „citarea în panou".

## Context

Răspunsul asistentului conține marcaje `[1]`, `[2]` … în text — cerute explicit modelului
(`open_notebook/ai/guguta/openrouter.py`) și validate înainte de publicare — iar interfața
adăuga sub răspuns lista surselor, cu locator brut (`{"paragraph":26}`).

Pentru elevul care citește răspunsul, ambele sunt zgomot: marcajele întrerup fraza, iar
lista expune detalii tehnice de implementare. Cerința formulată a fost să dispară din
răspuns, **fără** să se piardă funcționalitatea din spate.

## Decizie

1. Afișarea referințelor se oprește printr-un comutator: `SHOW_ANSWER_REFERENCES = false`
   în `frontend-guguta/lib/features.ts`.
2. Comutatorul afectează **doar prezentarea**: textul răspunsului se afișează fără marcaje
   (`withoutReferenceMarkers`), lista de surse nu se mai randează, iar citările nu se mai
   cer la încărcarea mesajelor.
3. **Nimic din backend nu se modifică**: promptul cere în continuare citări, validatorul le
   verifică (A12/A13), tabela `citations` continuă să le stocheze, iar endpointul
   `…/messages/{id}/citations` rămâne funcțional.
4. Marcajele se scot doar din răspunsul asistentului; întrebarea utilizatorului se afișează
   neatinsă, iar textul salvat în bază rămâne complet, cu marcaje.
5. Readucerea afișării înseamnă o singură linie schimbată, fără migrare și fără pierdere
   de date.

## Consecințe

- Răspunsul afișat este text curat; dovada păstrării funcției este că textul din bază are
  în continuare marcaje, iar citările validate se întorc pe API.
- A12/A13 rămân satisfăcute la nivel de date și contract. Criteriul „citările afișate în
  mesaj" din checklist-ul L5 este **suspendat deliberat** cât timp comutatorul e oprit.
- „Sursă eliminată" nu mai este vizibil în interfață cât timp comutatorul e oprit, deși
  mecanismul de rezolvare prin NotebookSource-ul destinatarului (ADR-0006 §6) rămâne intact.
- Un comutator viitor de interfață („arată sursele") poate afișa referințele deja existente
  fără nicio schimbare de backend.
- Efect secundar acceptat: numerele de 1–2 cifre între paranteze drepte scrise de model în
  alt scop (`[12]`) ar fi ascunse la afișare; anii (`[2024]`) și legăturile markdown
  `[1](url)` nu sunt afectate.