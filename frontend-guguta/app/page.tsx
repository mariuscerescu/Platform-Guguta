"use client";

import { useEffect, useState } from "react";
import { me } from "../lib/api";

export default function LandingPage() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    void me().then((u) => setAuthed(u !== null));
  }, []);

  return (
    <section className="hero" aria-labelledby="hero-title">
      <h1 id="hero-title">
        Învață <span className="gradient-word">Orice</span>
      </h1>
      <p>
        Partenerul tău de învățare, groundat în materialele în care ai
        încredere — carnete digitale cu răspunsuri citate, pentru elevii
        Republicii Moldova.
      </p>
      {authed === null ? (
        <span className="hero-cta" style={{ opacity: 0.6 }}>Se încarcă…</span>
      ) : authed ? (
        <a href="/app" className="hero-cta">Deschide Guguță</a>
      ) : (
        <a href="/login" className="hero-cta">Începe cu Guguță</a>
      )}
    </section>
  );
}
