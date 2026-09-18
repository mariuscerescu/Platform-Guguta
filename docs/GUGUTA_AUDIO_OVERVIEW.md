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
3. Scenariul este trimis exclusiv serviciului local MOSS-TTS.
4. Fișierul WAV este salvat în stocarea privată și devine disponibil în Studio.

## Serviciul vocal local

Integrarea folosește checkpointul exact
`OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5`, servit prin endpointul local
OpenAI-compatible `/v1/audio/speech` oferit de SGLang-Omni.

Într-un mediu Linux/WSL2 cu CUDA și suficient spațiu:

```bash
hf download OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5
sgl-omni serve \
  --model-path OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5 \
  --port 8000 \
  --vocoder_cuda_graph false
```

Workerul Docker accesează serviciul de pe host prin:

```dotenv
GUGUTA_MOSS_TTS_BASE_URL=http://host.docker.internal:8000
```

Configurația refuză deliberat URL-uri TTS externe. Astfel, scenariul derivat
din materialele elevului nu poate fi trimis accidental către un serviciu vocal
de pe internet.

## Resurse

Checkpointul BF16 are 5B parametri și include codecul MOSS Audio Tokenizer v2.
Fișierele modelului ocupă aproximativ 9,12 GB. Pentru model, mediul Python,
PyTorch/CUDA, cache și fișiere temporare trebuie rezervate:

- minimum practic: GPU cu 16 GB VRAM, 32 GB RAM și 20 GB liberi pe SSD;
- recomandat pentru producție: GPU cu 24 GB VRAM, 64 GB RAM și 30–40 GB
  liberi pe SSD.

GPU-ul actual cu 8 GB VRAM nu poate încărca în mod sigur checkpointul BF16
integral. CPU offload sau o cuantizare realizată de terți poate reduce necesarul
de VRAM, dar ar schimba profilul de performanță și trebuie validată separat.

## Ce mai trebuie făcut pentru activarea modelului real

- [ ] Se eliberează minimum 30 GB pe SSD-ul folosit pentru modelele Hugging
  Face și mediul Python.
- [ ] Se alocă un GPU NVIDIA cu minimum 16 GB VRAM; pentru producție se
  recomandă 24 GB VRAM și 64 GB RAM.
- [ ] Se instalează într-un mediu Linux sau WSL2 driverul NVIDIA, CUDA și un
  mediu Python izolat compatibil cu versiunea PyTorch cerută de MOSS-TTS.
- [ ] Se instalează `huggingface_hub`, MOSS-TTS și SGLang-Omni conform
  documentației oficiale.
- [ ] Se descarcă checkpointul exact
  `OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5` într-un director persistent,
  nu în stratul efemer al unui container.
- [ ] Se pornește serviciul pe portul `8000`, accesibil numai local. Pentru
  servere cu memorie limitată se păstrează `--vocoder_cuda_graph false`.
- [ ] Se verifică endpointul înainte de pornirea workerului:

  ```bash
  curl -X POST http://localhost:8000/v1/audio/speech \
    -H "Content-Type: application/json" \
    -d '{"model":"OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5","voice":"default","language":"Romanian","input":"Bun venit pe platforma Guguță."}' \
    --output test-moss.wav
  ```

- [ ] Se configurează workerul cu
  `GUGUTA_MOSS_TTS_BASE_URL=http://host.docker.internal:8000` și se repornește
  containerul worker.
- [ ] Se generează din interfață câte un Audio Overview **Brief** și **Deep
  Dive**, verificând limba română, durata, playerul, descărcarea și reîncercarea
  după o eroare simulată.
- [ ] Se măsoară timpul de generare și vârful de VRAM/RAM pentru un singur job.
  Concurența rămâne `1` până când măsurătorile arată că GPU-ul poate procesa mai
  multe cereri fără OOM.
- [ ] Serviciul MOSS este configurat să pornească automat și să aibă un health
  check. Portul `8000` nu se publică pe internet.

Referințe oficiale:

- https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5
- https://github.com/sgl-project/sglang-omni/blob/main/docs/cookbook/moss_tts_local.md
