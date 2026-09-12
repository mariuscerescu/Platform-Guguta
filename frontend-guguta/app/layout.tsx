import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { withBase } from "../lib/paths";

export const metadata: Metadata = {
  title: "Guguță — Carnete digitale",
  description:
    "Platforma Guguță: carnete digitale pentru elevii Republicii Moldova.",
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="ro-MD">
      <body>
        {/*
          Curăță marcajele pe care le injectează extensiile de browser în DOM
          înainte ca React să hidrateze (`bis_skin_checked`, `bis_register`,
          `__processed_<uuid>__` — semnătura Bitdefender și a altora).

          De ce e nevoie: React compară HTML-ul de pe server cu randarea din
          browser. Atributele străine apar doar în DOM, deci React raportează o
          nepotrivire de hidratare deși aplicația nu are niciun defect.
          `suppressHydrationWarning` nu ajută aici — a fost măsurat: extensia
          marchează și elemente imbricate, inclusiv noduri interne Next.js.

          Se pot șterge în siguranță: sunt simple marcaje de evidență ale
          extensiei, nu influențează protecția ei și nu au legătură cu datele
          aplicației. Dacă vrei să scapi de tot de script, dezactivează extensia
          pentru localhost — atunci nu mai e nimic de curățat.
        */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){
  var PREFIXES = ["bis_", "__processed_"];
  function matches(name){
    for (var i = 0; i < PREFIXES.length; i++) {
      if (name.indexOf(PREFIXES[i]) === 0) return true;
    }
    return false;
  }
  function clean(){
    var els = document.getElementsByTagName("*");
    for (var i = 0; i < els.length; i++) {
      var attrs = els[i].attributes;
      for (var j = attrs.length - 1; j >= 0; j--) {
        if (matches(attrs[j].name)) els[i].removeAttribute(attrs[j].name);
      }
    }
  }
  document.addEventListener("DOMContentLoaded", function(){
    clean();
    setTimeout(clean, 250);
  });
})();`,
          }}
        />
        <header className="header">
          <a href={withBase("/")} className="wordmark" aria-label="Guguță">
            <span>Guguță</span>
          </a>
          <nav className="top-nav" aria-label="Navigare principală">
            <a href={withBase("/import")}>Importă</a>
          </nav>
          {/*
            Header-ul nu are buton de cont: intrarea în cont stă doar pe pagina
            de start (app/page.tsx), ca să nu urmărească utilizatorul pe fiecare
            pagină. Cine vrea să intre în cont ajunge acolo prin sigla „Guguță".
          */}
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
