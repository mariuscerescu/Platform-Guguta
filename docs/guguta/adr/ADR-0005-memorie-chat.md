# ADR-0005: Memoria conversațiilor — mesaje în PostgreSQL, fără SqliteSaver

Stare: acceptat · Data: 6 septembrie 2026
Referințe: GHID_IMPLEMENTARE_LLM.md §7.3; EVALUARE §4.3.

## Context

Upstream păstrează checkpointurile LangGraph ale chatului în SQLite local (`SqliteSaver`, `LANGGRAPH_CHECKPOINT_FILE`) — `graphs/chat.py` și `graphs/source_chat.py`. Această memorie este globală, neizolată pe utilizator și nu migrează odată cu tabelele. Guguță nu poate rezuma o conversație dintr-o stare la care alt utilizator are acces sau care ocolește verificarea proprietății.

## Decizie

1. **Mesajele din PostgreSQL sunt singura sursă durabilă de adevăr** a conversațiilor (`chat_sessions`, `chat_messages`, `citations`).
2. Contextul promptului se **reconstruiește explicit pe server** la fiecare generare, din: mesajele sesiunii (bujon de istoric), fragmentele autorizate ale reviziei curente de context (`context_revision`), și instrucțiunea de sistem. MVP nu preia automat checkpointul SQLite upstream.
3. `context_revision` crește la orice schimbare de surse/selecție; reviziile vechi nu reintră în model. O generare în curs pe revizie veche se oprește sau se marchează anulată; ce a fost deja afișat rămâne istoric.
4. Checkpointuri LangGraph persistente (PostgresSaver) se introduc **numai dacă** un flux dovedit le cere; atunci: namespace derivat pe server (utilizator/carnet/sesiune), verificare de acces înainte de load/resume, revizie de context în namespace, strategie de ștergere documentată. ID-ul de thread nu este control de acces.
5. Generările simultane pe aceeași sesiune se serializează sau se resping, pentru istoric ordonat.
6. Streamingul transmite evenimente tipizate (început, delta, citare, final, eroare/anulare); mesajul nu se marchează complet înainte de salvarea finală.

## Consecințe

- Dependența `langgraph-checkpoint-sqlite` rămâne pentru codul upstream neportat până la L8; codul Guguță nu o folosește.
- Istoricele de chat upstream din SQLite nu se transferă implicit; orice import de conversații vechi e operație separată cu reconciliere (MIGRATION_INVENTORY.md).
- Testele A/B verifică și checkpointuri/streamuri, nu doar tabele.
