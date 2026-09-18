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
OpenAI-compatible `/v1/audio/speech`. Serviciul folosește o înregistrare
românească validată drept referință zero-shot; vocea și checkpointurile rămân
în afara imaginilor Docker și nu sunt salvate în Git.

În deploymentul curent, Compose montează read-only mediul MOSS-TTS deja
instalat, modelul, codecul v2 și vocea de referință. Serviciul rulează pe GPU 1
și nu publică niciun port pe gazdă.

Workerul accesează serviciul prin rețeaua privată a platformei:

```dotenv
GUGUTA_MOSS_TTS_RUNTIME_ROOT=/home/jupyter-marius/Test TTS modes
GUGUTA_MOSS_TTS_REFERENCE_AUDIO_HOST=/home/jupyter-marius/Test TTS modes/reference/recording_5_48khz_stereo.wav
GUGUTA_MOSS_TTS_BASE_URL=http://moss-tts:8000
GUGUTA_MOSS_TTS_REFERENCE_AUDIO=/voices/romanian.wav
GUGUTA_MOSS_TTS_GPU=1
```

Endpointul vocal trebuie să rămână în rețeaua privată a platformei. Astfel,
scenariul derivat din materialele elevului nu este trimis către un serviciu
vocal public.

## Activare și verificare

- [ ] Directorul de runtime conține `.venv`, checkpointul exact
  `OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5` și
  `MOSS-Audio-Tokenizer-v2`.
- [ ] Înregistrarea românească de referință este WAV PCM, 48 kHz stereo și
  poate fi citită de Docker.
- [ ] Se pornește serviciul și se așteaptă healthcheck-ul (încărcarea inițială
  a modelului poate dura câteva minute):

  ```bash
  sudo docker-compose --project-name guguta-edu \
    -f deploy/edu-platform/docker-compose.yml up -d moss-tts
  sudo docker-compose --project-name guguta-edu \
    -f deploy/edu-platform/docker-compose.yml ps
  ```

- [ ] Se verifică endpointul din rețeaua privată:

  ```bash
  sudo docker exec guguta-edu_worker_1 python -c \
    "import urllib.request; print(urllib.request.urlopen('http://moss-tts:8000/healthz').read().decode())"
  ```

- [ ] Se reconstruiește și se repornește workerul după schimbarea clientului.
- [ ] Se generează din interfață câte un Audio Overview **Brief** și **Deep
  Dive**, verificând limba română, durata, playerul, descărcarea și reîncercarea
  după o eroare simulată.
- [ ] `moss-tts` apare `healthy`; portul `8000` nu este publicat pe gazdă.

Referințe oficiale:

- https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5
- https://github.com/sgl-project/sglang-omni/blob/main/docs/cookbook/moss_tts_local.md
