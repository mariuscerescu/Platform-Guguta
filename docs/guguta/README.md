# Guguță — setul canonic de documentație

Revizie: 1.0 · 6 septembrie 2026

Acest director este **sursa canonică** a documentației Guguță în fork, conform
[GHID_IMPLEMENTARE_LLM.md](GHID_IMPLEMENTARE_LLM.md) §0.2: documentele din
directorul părinte al checkoutului au fost incluse aici într-un singur set
versionat, iar legăturile au fost actualizate.

## Conținut

| Document | Rol |
| --- | --- |
| [SPECIFICATII_GUGUTA.md](SPECIFICATII_GUGUTA.md) | Cerințe și comportament; autoritatea principală pentru produs. |
| [EVALUARE_OPEN_NOTEBOOK_PENTRU_GUGUTA.md](EVALUARE_OPEN_NOTEBOOK_PENTRU_GUGUTA.md) | Componente existente, limite și migrare. |
| [GHID_IMPLEMENTARE_LLM.md](GHID_IMPLEMENTARE_LLM.md) | Instrucțiuni concrete de execuție. |
| [GUGUTA_IMPLEMENTATION_CHECKLIST.md](GUGUTA_IMPLEMENTATION_CHECKLIST.md) | Progresul implementării L0–L10. |
| [IDEI_UI_ADAPTIV.md](IDEI_UI_ADAPTIV.md) | Propuneri: interfață adaptată vârstei și scena vie care reacționează la conversație. |
| [PLAN_INTEGRARE_PLAYQUIZ_COM.md](PLAN_INTEGRARE_PLAYQUIZ_COM.md) | Plan: export de quiz și cont automat către play-quiz.com; înlocuiește integrarea locală (ADR-021). |
| [PLAN_SESIUNI_CLOUD.md](PLAN_SESIUNI_CLOUD.md) | Sarcini cu prompturi gata pentru sesiuni cloud Claude Code sau Codex; pașii de conectare GitHub. |
| [DEPLOYMENT_READINESS_CHECKLIST.md](DEPLOYMENT_READINESS_CHECKLIST.md) | Dovezi necesare lansării. |
| [ANALIZA_OSS.md](ANALIZA_OSS.md) | Justificarea alegerii bazei open-source. |
| [adr/](adr/) | Arhitectura decisă (ADRs Guguță). |
| [DECIZII_EXTERNE.md](DECIZII_EXTERNE.md) | Decizii externe încă necesare, cu responsabil și termen. |
| [DIVERGENTE_UPSTREAM.md](DIVERGENTE_UPSTREAM.md) | Contradicții între regulile upstream și direcția Guguță. |
| [../..//MIGRATION_INVENTORY.md](../../MIGRATION_INVENTORY.md) | Inventarul datelor existente și maparea țintă. |

## Reguli

- Modificările de comportament încep în SPECIFICATII_GUGUTA.md; ghidul și
  checklistul se aliniază după.
- Nu se întrețin alte copii ale acestor documente care să evolveze separat.
  Instantaneele din directorul părinte al checkoutului au servit ca sursă la
  copierea din 6 septembrie 2026; de la această revizie, versiunea din fork
  face autoritate pentru dezvoltare.
- Fiecare ADR are stare (acceptat / propus / înlocuit) și este legat de
  livrările din checklist.
