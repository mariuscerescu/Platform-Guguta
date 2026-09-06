# ADR-0003: Identitate OIDC + PKCE, sesiuni opace server-side

Stare: acceptat · Data: 6 septembrie 2026
Referințe: GHID_IMPLEMENTARE_LLM.md §4, SPECIFICATII_GUGUTA.md §3.

## Context

Upstream are un model single-user: parolă comună de instanță (`APP_PASSWORD`) în middleware și CORS deschis — explicit „dev defaults, not production hardening”. Guguță introduce utilizatori independenți (elevi, editori de catalog, administratori), proprietate pe carnete și refuz pe server pentru accesul încrucișat.

## Decizie

1. Autentificarea delegată către un **furnizor OIDC** prin Authorization Code + PKCE, cu `state` și `nonce`; verificarea issuer, audience, semnăturii și expirării.
2. Asocierea contului local se face pe **issuer + subject**, nu doar pe email.
3. Sesiunea aplicației este **opacă, server-side**: token aleatoriu cu entropie suficientă, stocat hashuit în `sessions`, cookie `HttpOnly` (+ `Secure` pe HTTPS, `SameSite` potrivit fluxului). Fără tokenuri de autentificare în localStorage.
4. Protecție CSRF pentru mutațiile bazate pe cookie, cu verificarea Origin.
5. Expirare de inactivitate și absolută; logout invalidând sesiunea; blocarea contului sau retragerea rolului invalidează sesiunile existente.
6. **Fără parole proprii în MVP**; recuperarea accesului se configurează la furnizorul de identitate. Furnizorul nu controlează direct `owner_id`.
7. Rolurile (utilizator, editor de catalog, administrator) sunt atribute server-side ale contului; permisiunile se verifică pe server pentru fiecare resursă, indiferent de UI.
8. Pentru teste există un issuer fals controlat și, numai în mod explicit local, login cu utilizatori sintetici; **startup-ul staging/production refuză modul de autentificare de test**.

## Consecințe

- Alegerea furnizorului identitate și regulile pentru minori sunt decizii de pilot (DECIZII_EXTERNE.md), nu blocate în fundație.
- Migratorul, API-ul și workerul folosesc roluri DB distincte (ADR-0007); identitatea aplicativă nu se confundă cu rolul de bază de date.
- Contradicția cu AGENTS.md upstream (parolă comună, CORS deschis) este consemnată în DIVERGENTE_UPSTREAM.md; regulile upstream rămân pentru codul neportat, nu pentru fundația Guguță.
