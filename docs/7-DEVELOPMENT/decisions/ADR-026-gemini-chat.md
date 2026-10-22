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

Nu se trimit parametrii de rutare/ZDR OpenRouter către Google. Contul Google
trebuie configurat conform condițiilor proiectului; integrarea nu promite
retenție zero. Cheile nu ajung în interfață, erori sau Git.

Referințe: [compatibilitate API](https://ai.google.dev/gemini-api/docs/openai),
[semnături](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures).
