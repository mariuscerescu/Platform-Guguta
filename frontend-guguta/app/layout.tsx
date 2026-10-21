import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "katex/dist/katex.min.css";
import "./globals.css";
import "./dark-theme.css";
import "./components/education-companion.css";
import "./components/landing-companion.css";
import "./components/companion-chat.css";
import "./theme.css";
import SiteHeader from "./components/SiteHeader";
import SiteFooter from "./components/SiteFooter";
import CookieNotice from "./components/CookieNotice";
import { THEME_INIT_SCRIPT } from "../lib/theme";

export const metadata: Metadata = {
  title: "Platforma educațională Guguță",
  description:
    "Platforma educațională Guguță pentru elevii Republicii Moldova.",
};

export const viewport: Viewport = {
  colorScheme: "light dark",
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="ro-MD" data-theme="dark" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
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
        {/* Header-ul își schimbă culoarea și butonul după rută (vezi SiteHeader). */}
        <SiteHeader />
        <main className="container">{children}</main>
        <SiteFooter />
        <CookieNotice />
      </body>
    </html>
  );
}
