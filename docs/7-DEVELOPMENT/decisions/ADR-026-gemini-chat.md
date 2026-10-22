# ADR-026: Gemini API direct pentru chat și resurse

Data: 22 octombrie 2026. Stare: acceptat la cererea utilizatorului.

Furnizorul `GUGUTA_CHAT_PROVIDER=gemini` folosește direct endpointul Google
`https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`.
Modelul implicit este `gemini-3.8-flash`, cu gândire `medium`.
Cheia server-side este `GUGUTA_GEMINI_API_KEY`; modelul și nivelul se configurează
prin `GUGUTA_GEMINI_CHAT_MODEL` și `GUGUTA_GEMINI_THINKING_LEVEL`.

Se reutilizează prompturile, contractul JSON, verificarea citărilor, imaginile
autorizate, limitele agentului și revizuirea răspunsului. Semnăturile opace ale
apelurilor de unelte și intrările exacte ale acestor apeluri rămân în istoricul
temporar al agentului; raționamentul nu este afișat sau salvat ca mesaj al elevului.
Bugetul de ieșire implicit de 16384 include gândirea și răspunsul vizibil,
inclusiv la planificare, pentru a nu întrerupe JSON-ul prin limita veche de 300.

Aceeași selecție este respectată de quizuri, flashcards și scenariile audio.
Qwen pentru embedding/reranking, dictarea și furnizorii conversației vocale
nu depind de această selecție. Nu există fallback automat către alt model.
OpenRouter rămâne disponibil prin configurație pentru compatibilitate.

Pentru latență, saluturile simple fără fișiere noi au un răspuns local, fără
căutare și fără apel AI; întrebările și mesajele cu atașamente păstrează fluxul
de dovezi. Agentul primește catalogul deja autorizat pentru a căuta direct,
fără un apel de descoperire duplicat. În producție, Gemini folosește o singură
generare cu `medium`, fără a doua revizuire AI; validarea citărilor rămâne activă.
Erorile tranzitorii Google, inclusiv HTTP 500, se reîncearcă limitat. Jurnalele
rețin numai durata, etapa și codul HTTP, fără întrebări sau corpuri de răspuns.

Nu se trimit parametrii de rutare/ZDR OpenRouter către Google. Contul Google
trebuie configurat conform condițiilor proiectului; integrarea nu promite
retenție zero. Cheile nu ajung în interfață, erori sau Git.

Conexiunile PostgreSQL API/worker dezactivează JIT la nivel de conexiune,
păstrând opțiunile DSN existente și toate politicile RLS. O interogare reală de
catalog a măsurat 7110 ms cu JIT (7081 ms compilare) și 1,338 ms fără JIT;
această setare nu modifică schema, datele sau configurația globală PostgreSQL.

Referințe: [compatibilitate API](https://ai.google.dev/gemini-api/docs/openai),
[semnături](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures).
