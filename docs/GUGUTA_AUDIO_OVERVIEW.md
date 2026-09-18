# Audio Overview Guguță

Audio Overview generează un monolog educațional în română din materialele
selectate ale unui Carnet digital. Sunt disponibile două formate, ambele cu un
singur speaker:

- **Brief** — aproximativ 2 minute, cu ideile esențiale.
- **Deep Dive** — aproximativ 8–12 minute, cu explicații, conexiuni, exemple și
  recapitulare.

Fluxul este asincron:

1. API-ul validează că materialele aparțin utilizatorului și sunt procesate.
2. Un job durabil generează scenariul pe baza textului extras din surse.
3. Scenariul este trimis serviciului privat MOSS-TTS de pe serverul GPU.
4. Fișierul WAV este salvat în stocarea privată și devine disponibil în Studio.

## Serviciul vocal pe serverul GPU

Integrarea folosește checkpointul exact
`OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5`, servit prin endpointul privat
OpenAI-compatible `/v1/audio/speech` oferit de SGLang-Omni.

```bash
hf download OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5
sgl-omni serve \
  --model-path OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5 \
  --port 8000
```

Workerul accesează serviciul prin rețeaua privată a platformei:

```dotenv
GUGUTA_MOSS_TTS_BASE_URL=http://moss-tts:8000
```

Endpointul vocal trebuie să rămână în rețeaua privată a platformei. Astfel,
scenariul derivat din materialele elevului nu este trimis către un serviciu
vocal public.

## Ce mai trebuie făcut pentru activarea modelului real

- [ ] Se instalează MOSS-TTS și SGLang-Omni pe serverul GPU conform
  documentației oficiale.
- [ ] Se descarcă checkpointul exact
  `OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5`.
- [ ] Se pornește serviciul pe portul `8000`, accesibil numai din rețeaua
  privată a platformei.
- [ ] Se verifică endpointul înainte de pornirea workerului:

  ```bash
  curl -X POST http://localhost:8000/v1/audio/speech \
    -H "Content-Type: application/json" \
    -d '{"model":"OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5","voice":"default","language":"Romanian","input":"Bun venit pe platforma Guguță."}' \
    --output test-moss.wav
  ```

- [ ] Se configurează workerul cu
  `GUGUTA_MOSS_TTS_BASE_URL=http://moss-tts:8000` și se repornește
  containerul worker.
- [ ] Se generează din interfață câte un Audio Overview **Brief** și **Deep
  Dive**, verificând limba română, durata, playerul, descărcarea și reîncercarea
  după o eroare simulată.
- [ ] Serviciul MOSS este configurat să pornească automat și să aibă un health
  check. Portul `8000` nu este publicat pe internet.

Referințe oficiale:

- https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5
- https://github.com/sgl-project/sglang-omni/blob/main/docs/cookbook/moss_tts_local.md
