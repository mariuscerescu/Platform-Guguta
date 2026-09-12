# ADR-0013: Întrebarea merge și fără materiale în carnet

Stare: acceptat · Data: 12 septembrie 2026
Referințe: ADR-0005 (memoria chat), ADR-0008 (OpenRouter), ADR-0009 (referințe
dezactivate în răspuns); `api/services/guguta/chat.py`,
`open_notebook/ai/guguta/chat.py`, `open_notebook/ai/guguta/openrouter.py`.

## Context

Un carnet nou pornește fără materiale, iar copilul ajunge în chat înainte de a fi
încărcat ceva. Regula veche refuza întrebarea:

- `send_message` și `send_message_stream` numărau materialele selectate și
  aruncau `SourcesRequired` („Niciun fragment găsit în materialele selectate."),
  tradus în HTTP 422 cu codul `sources_required`;
- furnizorii refuzau și ei, independent, când recuperarea întorcea zero
  fragmente — `MockChatProvider` și `OpenRouterChatProvider` aveau fiecare câte
  o cale de „Nu găsesc informația în materialele selectate ale carnetului."

Efectul: butonul de trimitere părea stricat. Se putea scrie, dar orice întrebare
prima același text, fără ca mesajul utilizatorului să fie măcar salvat (refuzul
se producea înainte de inserare). Situația apare în două cazuri, nu doar la
carnetul gol: materiale încărcate dar neselectate pentru chat, și întrebări care
nu au legătură cu materialele selectate — caz în care recuperarea întoarce,
corect, zero fragmente.

## Decizie

1. **Refuzul dispare din serviciu.** Ambele verificări „există materiale
   selectate?" au fost scoase: mesajul se salvează mereu, iar răspunsul se
   generează mereu. Clasa `SourcesRequired` și handler-ul ei de 422 rămân în
   vocabularul de erori al API-ului, dar nu mai sunt ridicate de niciun drum de
   cod.
2. **Furnizorii răspund din cunoștințele generale când nu au fragmente.**
   `SYSTEM_PROMPT` descrie explicit ambele situații: cu fragmente întemeiază
   răspunsul pe ele și citează; fără fragmente răspunde general și spune asta.
   Instrucțiunea către OpenRouter primește aceeași clauză, plus regula că, la
   listă vidă de fragmente, `cited` este `[]` și nu se pun marcaje `[1]`.
3. **Eticheta de proveniență o pune serverul, nu modelul.** La listă vidă de
   fragmente, `OpenRouterChatProvider` adaugă în fața răspunsului
   `FARA_MATERIALE_PREFIX` („Nu am materiale din carnet care să acopere
   întrebarea, așa că îți răspund din cunoștințele generale:"). Prima verificare
   în browser, cu furnizorul real, a arătat de ce: modelul a răspuns corect, dar
   a omis să spună de unde vine răspunsul. Eticheta nu depinde de bunăvoința lui.
4. **Validarea citărilor tolerează contextul vid.** Marcajele strecurate de model
   într-un răspuns fără fragmente sunt șterse, iar `cited` este forțat `[]`,
   înainte de verificarea de coerență dintre marcaje și indici — altfel un
   răspuns general altfel bun ar fi respins ca invalid.
5. **Versiunile de prompt cresc**: `guguta-mock-2` și `guguta-openrouter-2`.
   `prompt_version` se salvează pe fiecare mesaj de asistent, deci schimbarea
   rămâne vizibilă în istoric.

## Consecințe

- Fără materiale nu există citări: `cited` rămâne 0 și nu se afișează referințe.
  Verificarea de coerență a marcajelor funcționează în continuare, pentru că
  mulțimea vidă de marcaje este egală cu mulțimea vidă de indici.
- Calitatea răspunsului general nu este verificată de materiale, deci poate fi
  greșită. De aceea eticheta e obligatorie: elevul știe mereu când răspunsul nu
  vine din carnetul lui. Aceeași regulă rămâne valabilă și pentru întrebările
  fără răspuns în materiale (ADR-0009).
- Recuperarea rulează în continuare la fiecare întrebare, deci fiecare întrebare
  costă o înglobare. Dacă furnizorul de înglobare nu corespunde spațiului
  vectorial înregistrat, căutarea ridică eroare și cererea se termină cu 500
  „Eroare internă." — nu cu un refuz de materiale (observat în timpul verificării,
  când API-ul local rula cu furnizorul `hash` peste o bază indexată cu OpenRouter).
- Testele s-au schimbat odată cu regula: testul care aștepta 422 cu
  `sources_required` verifică acum că mesajul și răspunsul sunt salvate și că
  răspunsul spune de unde vine; un test nou de furnizor verifică eticheta și
  ștergerea marcajelor. Scenariul din browser e acoperit de
  `frontend-guguta/.tmp/verify-fara-materiale.mjs` (carnet fără materiale →
  întrebare → răspuns salvat și afișat, fără textul de refuz).
