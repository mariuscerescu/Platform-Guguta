# ADR-0004: Stocarea fișierelor — adaptor privat, filesystem în development

Stare: acceptat · Data: 6 septembrie 2026
Referințe: GHID_IMPLEMENTARE_LLM.md §6.1, §10.1; ANALIZA_OSS.md §5.

## Context

Upstream scrie fișierele în volumul `notebook_data` montat la `/app/data`, cu numelui original ca parte a căii. Guguță cere fișiere private, descărcare autorizată prin proxy, și ștergere controlată coordonată cu snapshoturi/importuri/joburi (invariantele 6–7 din specificații).

## Decizie

1. Interfață `StorageBackend` cu operații: scriere temporară, finalizare (commit), citire autorizată (stream), ștergere controlată, statistici de cotă.
2. Cheile (locațiile) sunt **generate de server** (UUID/random); numele original este metadată în `source_assets`, niciodată cale.
3. Implementări: `FilesystemStorage` (rădăcină privată în afara webrootului, pentru development și pilot pe un singur host, cu backup demonstrat) și adaptor de object storage pentru producție (se alege la stabilirea găzduirii — decizie externă).
4. Uploadul validează: tip real (magic bytes), mărime, număr de pagini, timeout; blochează path traversal, symlink-uri care ies din rădăcină, decomprimare excesivă și formate nepermise. MVP acceptă PDF cu text, DOCX, PPTX, TXT/Markdown și text introdus.
5. Nu se expun URL-uri publice permanente; downloadul trece prin proxy autorizat al API-ului. URL-urile semnate, dacă apar, au TTL scurt și fără promisiune de revocare instantanee.
6. Fișierele se șterg fizic numai în GC în două faze, când nu mai există referințe valide din carnete, șabloane, snapshoturi sau joburi (ADR-0006).
7. Hash-ul (SHA-256) se calculează pe server; hash-ul trimis de client nu dovedește drept de acces.

## Consecințe

- Volumul demo `notebook_data` upstream nu este folosit de stiva Guguță; există rădăcină separată configurabilă.
- Deduplicarea fizică a octeților este permisă intern și condiționată de compatibilitate; cota utilizatorului ia în calcul materialele logice, nu octeții deduplificați.
- Scanarea malware în pipeline înainte de starea „disponibilă” este obligatorie pentru pilot; motorul se alege separat.
