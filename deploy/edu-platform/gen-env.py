# -*- coding: utf-8 -*-
"""Generează deploy/edu-platform/.env (producție) cu secrete reale.

Cheia OpenRouter este preluată din .env.guguta.local FĂRĂ a fi afișată.
Scriptul tipărește fișierul rezultat cu secretele mascate, pentru verificare.
"""
import pathlib
import re
import secrets

REPO = pathlib.Path(r"D:\Disk D 13-09-25\CS\AI Guguta\Platforma Guguta\open-notebook")
TARGET = REPO / "deploy" / "edu-platform" / ".env"
LOCAL = REPO / ".env.guguta.local"
EXAMPLE = REPO / "deploy" / "edu-platform" / ".env.example"


def read_local(name: str) -> str:
    for line in LOCAL.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"lipsește {name} din {LOCAL}")


def token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


values = {
    "GUGUTA_SERVER_SECRET": token(36),
    "GUGUTA_CREDENTIAL_ENCRYPTION_KEYS": '{"k1": "%s"}' % token(32),
    "GUGUTA_PG_MIGRATOR_PASSWORD": token(24),
    "GUGUTA_PG_API_PASSWORD": token(24),
    "GUGUTA_PG_WORKER_PASSWORD": token(24),
    "GUGUTA_OPENROUTER_API_KEY": read_local("GUGUTA_OPENROUTER_API_KEY"),
}

# Pornim din șablon și completăm doar câmpurile goale marcate mai sus.
text = EXAMPLE.read_text(encoding="utf-8")
lines = []
for line in text.splitlines():
    key = line.split("=", 1)[0] if "=" in line and not line.startswith("#") else None
    if key in values:
        lines.append(f"{key}={values[key]}")
    elif key == "GUGUTA_CREDENTIAL_ENCRYPTION_KEYS":
        lines.append(line)
    else:
        lines.append(line)

text = "\n".join(lines)
text = text.replace(
    "# Publicare: https://tineri.math.md/edu-platform",
    "# Publicare: https://tineri.math.md/edu-platform\n"
    "# GENERAT automat cu secrete reale — nu urca acest fișier în Git.",
)
TARGET.write_text(text + "\n", encoding="utf-8")

# Verificare: toate variabilele obligatorii au valoare, apoi afișare mascată.
required = [
    "GUGUTA_ENVIRONMENT", "GUGUTA_AUTH_MODE", "GUGUTA_BASE_PATH",
    "GUGUTA_PUBLIC_ORIGIN", "GUGUTA_CORS_ORIGINS", "GUGUTA_SERVER_SECRET",
    "GUGUTA_CREDENTIAL_ENCRYPTION_KEYS", "GUGUTA_PG_MIGRATOR_PASSWORD",
    "GUGUTA_PG_API_PASSWORD", "GUGUTA_PG_WORKER_PASSWORD",
    "GUGUTA_CHAT_PROVIDER", "GUGUTA_EMBEDDING_PROVIDER",
    "GUGUTA_EMBEDDING_DIMENSION", "GUGUTA_OPENROUTER_API_KEY",
    "GUGUTA_OPENROUTER_CHAT_MODEL", "GUGUTA_OPENROUTER_EMBEDDING_MODEL",
]
parsed = {}
for line in text.splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        parsed[k.strip()] = v.strip()

missing = [k for k in required if not parsed.get(k)]
if missing:
    raise SystemExit("variabile fără valoare: " + ", ".join(missing))

print(f"scris: {TARGET}\n")
print("--- cu secretele mascate ---")
for line in text.splitlines():
    k = line.split("=", 1)[0] if "=" in line and not line.startswith("#") else ""
    if k in ("GUGUTA_SERVER_SECRET", "GUGUTA_PG_MIGRATOR_PASSWORD",
             "GUGUTA_PG_API_PASSWORD", "GUGUTA_PG_WORKER_PASSWORD"):
        print(f"{k}=<{len(parsed[k])} caractere>")
    elif k == "GUGUTA_CREDENTIAL_ENCRYPTION_KEYS":
        print(f'{k}={{"k1": "<{len(values["GUGUTA_CREDENTIAL_ENCRYPTION_KEYS"])} caractere JSON>"}}')
    elif k == "GUGUTA_OPENROUTER_API_KEY":
        key = parsed[k]
        print(f"{k}={key[:12]}…{key[-4:]}  ({len(key)} caractere)")
    else:
        print(line)
