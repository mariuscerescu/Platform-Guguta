# OpenRouter: confidențialitate și rutare rapidă

Configurație aplicată la 2026-10-07, conform ADR-018.

## Context

Aplicația folosește un client HTTP comun pentru chat, uneltele agentului,
embeddings, reranking și generarea materialelor Studio. Rutarea implicită
OpenRouter favorizează prețul; interzicerea antrenării pe date nu este suficientă
pentru a exclude retenția pentru monitorizare.

## Decizie

Clientul adaugă obligatoriu `provider.zdr=true` și
`provider.data_collection="deny"` la fiecare apel. Aceste valori prevalează
asupra payloadului primit și se păstrează la toate încercările. Cerințele pentru
unelte/JSON structurat și listele de provideri eligibili sunt păstrate. Dacă nu
există un endpoint compatibil, cererea eșuează controlat; nu se elimină
restricțiile și nu se schimbă automat modelul.

`GUGUTA_OPENROUTER_PROVIDER_SORT=throughput` ordonează providerii pentru
generare, verificarea răspunsului, quizuri, flashcarduri și scenarii audio.
`GUGUTA_OPENROUTER_INTERACTIVE_PROVIDER_SORT=latency` se aplică planificării
căutărilor, selectării uneltelor, embeddings și reranking. OpenRouter permite
un singur criteriu principal per apel. Pragurile configurabile
`GUGUTA_OPENROUTER_PREFERRED_MAX_LATENCY_SECONDS=3` și
`GUGUTA_OPENROUTER_PREFERRED_MIN_THROUGHPUT=50` favorizează endpointurile care
îndeplinesc ambele condiții, fără a exclude celelalte endpointuri ZDR.
Acestea sunt preferințe pe statisticile recente, fără garanție de timp maxim;
valoarea Python `None` omite preferința respectivă. Confidențialitatea este un
filtru obligatoriu, independent de aceste preferințe.

Antetul `X-OpenRouter-Cache: false` dezactivează explicit cache-ul de răspunsuri,
inclusiv dacă un preset îl activează. Destinațiile HTTP sunt limitate la cele
trei endpointuri folosite de aplicație, iar redirecturile sunt refuzate.
Mesajele și metadatele brute ale erorilor upstream nu ajung în răspunsurile API,
starea joburilor sau logurile aplicației: pot conține fragmente din input.

## Limite și configurarea contului

ZDR reprezintă politica declarată a endpointului în catalogul OpenRouter,
nu o verificare independentă a infrastructurii providerului. Politica ZDR
OpenRouter permite cache temporar al promptului în RAM la provider. Antetul
pentru cache OpenRouter nu controlează acest cache intern al providerului.
Aplicația nu garantează absența oricărei memorii temporare sau „securitate 100%”.

Administratorul contului trebuie să mențină **Input & Output Logging** oprit
în Observability și **OpenRouter Use of Inputs/Outputs** oprit în Privacy.
Aceste opțiuni sunt administrate la nivel de cont; clientul de inferență nu
verifică și nu modifică aceste setări. ZDR global la nivel de cont/organizație
este recomandat suplimentar pentru celelalte aplicații care folosesc cheia.
OpenRouter păstrează metadate de utilizare (tokenuri, costuri, latență), fără
conținutul prompturilor/răspunsurilor conform politicii publicate.

Materialele și conversațiile persistate în baza privată a aplicației rămân
necesare funcției de carnet. Embeddings, reranking, OCR, TTS și ASR rămân locale
în configurația serverului existent. Nu se modifică modelul sau prompturile.

## Verificare

Teste HTTP fără rețea verifică toate endpointurile, prioritatea configurației
private, păstrarea restricțiilor la retry, cerințele pentru unelte și JSON,
dezactivarea cache-ului, lipsa fallbackului la erori de eligibilitate și
redactarea erorilor, inclusiv HTTP 200 cu `error` în corp.

Validare la implementare: 81 teste țintite trecute, suita Guguță cu 221 teste
trecute și 2 teste live sărite implicit, Ruff și `git diff --check` fără erori.
Un smoke test live separat, exclusiv cu input sintetic, a verificat selectarea
uneltelor, generarea și revizia cu `google/gemma-4-31b-it`, toate trei cu
politica obligatorie. Endpointul selectat, ModelRun, era prezent în catalogul
ZDR. Întrebarea „Cum va fi în engleză ora 9 fix?” a primit traducerea corectă
fără citări inventate. Cele trei apeluri individuale au durat 1,24–1,47 secunde
în acel test; acest eșantion nu constituie o garanție de performanță.

Surse oficiale consultate la data deciziei:

- [Provider Selection](https://openrouter.ai/docs/guides/routing/provider-selection)
- [Zero Data Retention](https://openrouter.ai/docs/guides/features/zdr)
- [Response Caching](https://openrouter.ai/docs/guides/features/response-caching)
- [Data Collection](https://openrouter.ai/docs/guides/privacy/data-collection)
- [Input & Output Logging](https://openrouter.ai/docs/guides/features/input-output-logging)
