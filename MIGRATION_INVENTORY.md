# MIGRATION_INVENTORY — inventarul datelor existente și maparea țintă

Data: 6 septembrie 2026 · bază: Open Notebook 1.14.0, commit `8297bb22e2eaeb0d8feafc0538f0d736453571d4`
Regulă: inventar fără afișarea conținutului sau a secretelor; datele existente nu sunt considerate dispensabile (GHID §2).

## 1. Surse de date identificate

| Sursă | Locație | Conținut observat | Stare la inventariere |
| --- | --- | --- | --- |
| Volume demo SurrealDB | `open-notebook/surreal_data/` | 7 fișiere (~0,63 MiB): date rocksdb + log | Prezent; stack demo a rulat local (containere upstream) |
| Fișiere notebook | `open-notebook/notebook_data/` | 11 fișiere (~0,25 MiB): 2×DOCX, DB SurrealDB auxiliar (msgpack), SQLite checkpoints | Prezent |
| Checkpointuri chat LangGraph | `open-notebook/notebook_data/sqlite-db/checkpoints.sqlite` | 4 KiB (practic gol) | Prezent; `LANGGRAPH_CHECKPOINT_FILE` |
| Git | `open-notebook/.git` | HEAD `8297bb2` pe `main`; fără modificări locale pe fișiere urmărite | Curat |
| Secrete necesare decriptării cheilor criptate | variabila de mediu `OPEN_NOTEBOOK_ENCRYPTION_KEY` a instanței demo | Existență de verificat la transfer, fără citirea valorii | Nu se exportă în Git/seeds |

## 2. Backup și restaurare

- Backup coerent făcut la `Platforma Guguta/backups/pre-migration-20260906-112923/`
  (`notebook_data.zip`, `surreal_data.zip` + `.sha256`), creat **cu serviciile oprite**
  (Docker daemon oprit la momentul copierii), deci fără scriitori activi.
- Restaurare verificată: dezarhivare completă + comparare SHA-256 per fișier —
  18/18 fișiere identice.
- Volumele originale rămân pe loc, neatinse; nu se rulează down cu ștergere de volume.

## 3. Maparea țintă Guguță

| Tip dată vechi | Mapare țintă | Notă |
| --- | --- | --- |
| Notebook (`notebook`) | `digital_notebooks` | fără proprietar single-user implicit; necesită atribuire proprietar desemnat |
| Source (`source`) | `source_assets` + `material_versions` + `notebook_sources` | separarea conform ADR-0006 |
| Source insights / embeddings | `processing_artifacts`, `chunks`, `embeddings` | reindexare probabilă; spațiu vectorial nou |
| Notes (`note`) | `notes` | private |
| Chat messages / sessions | `chat_sessions`, `chat_messages`, `citations` | checkpointurile SQLite NU se transferă implicit (ADR-0005) |
| Credentials (chei criptate) | `admin` configurare AI Guguță | necesită `OPEN_NOTEBOOK_ENCRYPTION_KEY` pentru decriptare; operație separată, aprobată |
| Transformări / podcasturi | nu se transferă în MVP | amânate cu dezactivare server-side |
| Fișiere încărcate (notebook_data) | `StorageBackend` privat (ADR-0004) | copiate cu hash recalculat pe server |

## 4. Decizii și reconciliere

- **D-08 (DESCHISĂ)**: transferul sau excluderea datelor demo cere proprietar
  desemnat și decizie explicită. Datele single-user nu se atribuie automat
  tuturor utilizatorilor.
- Orice transfer viitor: export controlat → dry-run → raport de reconciliere
  (număr/hash/referințe) → transfer aprobat. Până atunci volumele se păstrează
  conform retenției.
- Livrarea curentă (L0/L1) nu citește și nu mută niciun conținut din volumele demo.
