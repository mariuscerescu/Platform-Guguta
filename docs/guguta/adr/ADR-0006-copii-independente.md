# ADR-0006: Copii independente — SourceAsset / MaterialVersion / NotebookSource

Stare: acceptat · Data: 6 septembrie 2026
Referințe: SPECIFICATII_GUGUTA.md §5, §8, §9; EVALUARE §4.1.

## Context

În upstream, „asocierea” unei surse existente la alt notebook creează o relație către **același obiect**, iar ștergerea diferențiază doar sursele exclusive de cele partajate. Contractul Guguță cere copii independente: importul/instanțierea transferă materialele, fără chat, notițe sau memorie, iar modificările autorului nu se propagă (C13–C15, A03, A09).

## Decizie

1. Separația în trei niveluri:
   - **SourceAsset** — octeți/text imuabili, hash pe server, locator privat, MIME detectat, mărime; nu acordă singur drept de acces.
   - **MaterialVersion** — asociere la SourceAsset + metadate versionate de proveniență/atribuire/drepturi; versiunile publicate sau capturate în snapshoturi nu se modifică niciodată.
   - **NotebookSource** — asocierea personală a unui MaterialVersion la un carnet, cu **ID propriu, nume local și ordine**; fiecare copie primește NotebookSource nou.
2. Copierea (instanțiere/import) reutilizează MaterialVersion-ul capturat (și, unde e compatibil, artefactele de procesare), dar **nu** copiază cheia FK către sursa personală a autorului, nu copiază chat, notițe, insight-uri, memorie sau permisiuni.
3. **Fără cascade delete** de la carnet către SourceAsset/MaterialVersion. Ștergerea unei asocieri elimină doar NotebookSource-ul; octeții rămân cât timp există referințe din alte carnete, șabloane publicate, snapshoturi active sau joburi în curs.
4. GC în două faze: candidat după retenție, apoi reverificarea referințelor cu coordonarea importurilor; retry sigur.
5. Revocarea snapshotului blochează importurile noi; copiile finalizate păstrează referințe proprii. Ștergerea carnetului autorului revocă pachetele active; ștergerea contului la fel, fără a șterge copiile destinatarilor.
6. Citările rezolvă întotdeauna prin NotebookSource-ul destinatarului, nu prin ID-ul sursei autorului; sursa eliminată afișează „Sursă eliminată”.
7. `context_revision` la nivel de carnet crește la eliminare/înlocuire/schimbare de selecție; mesajele vechi rămân istoric vizibil, dar nu reintră în model.

## Consecințe

- Snapshotul (ShareSnapshot) fixează **MaterialVersion**, nu NotebookSource — un material eliminat din carnetul autorului rămâne referit de snapshotul activ (A18/A21).
- „Începe din nou” creează carnet nou din versiunea publicată curentă a șablonului; carnetul vechi rămâne intact.
- Cota ia în calcul materialele logice; deduplicarea fizică nu ocolește limitele (A20).
