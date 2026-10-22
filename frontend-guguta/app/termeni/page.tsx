import type { Metadata } from "next";
import { withBase } from "../../lib/paths";

export const metadata: Metadata = { title: "Termeni de utilizare · Guguță" };

export default function TermsPage() {
  return (
    <article className="legal">
      <h1>Termeni de utilizare</h1>
      <p className="muted">Versiunea 2026-10-22. Platforma este în dezvoltare activă, în cadrul unui proiect de cercetare; instanța publică este de test.</p>

      <h2>1. Ce este Guguță</h2>
      <p>Guguță este o platformă educațională cu un tutore bazat pe inteligență artificială, care răspunde pe baza materialelor din carnetele tale și te ajută să exersezi. Nu înlocuiește profesorul și nu garantează corectitudinea fiecărui răspuns: verifică informațiile importante în manual sau cu profesorul.</p>

      <h2>2. Contul</h2>
      <ul>
        <li>Contul este personal. Parola este cheia de la carnetele tale: nu o spune nimănui.</li>
        <li>Pentru un elev sub 14 ani este necesară autorizarea reprezentantului legal atunci când înscrierea se bazează pe consimțământ. Fluxul actual de autorizare este provizoriu și se validează instituțional.</li>
        <li>Poți șterge contul oricând din <a href={withBase("/cont")}>Contul meu</a>.</li>
      </ul>

      <h2>3. Materialele tale</h2>
      <p>Încarci doar materiale pe care ai dreptul să le folosești (manuale, notițe, fișe de la profesor). Materialele rămân private, în carnetele tale; le poți partaja cu un cod pe care îl dai tu. Nu încărca date despre alte persoane fără acordul lor.</p>

      <h2>4. Comportament</h2>
      <p>Folosește platforma pentru învățare. Nu încerca să ocolești protecțiile, să supraîncarci serviciul sau să folosești tutorele pentru conținut dăunător. Conturile care încalcă aceste reguli pot fi suspendate.</p>

      <h2>5. Servicii partenere</h2>
      <p>Unele funcții folosesc servicii externe (modele de limbaj, conversație vocală, PlayQuiz). Înainte să folosești microfonul sau să trimiți un quiz către PlayQuiz, citește ce date pleacă din platformă în <a href={withBase("/confidentialitate")}>Politica de confidențialitate</a>.</p>

      <h2>6. Disponibilitate și răspundere</h2>
      <p>Serviciul este oferit „ca atare”, fără garanții de disponibilitate continuă. Facem copii de siguranță, dar păstrează și tu materialele importante. Echipa proiectului nu răspunde pentru deciziile luate exclusiv pe baza răspunsurilor tutorelui.</p>

      <h2>7. Contact</h2>
      <p>Întrebări și sesizări: <a href="mailto:tudor.bumbu@math.md">tudor.bumbu@math.md</a>. Pagina proiectului: <a href="https://tineri.math.md" rel="noopener" target="_blank">tineri.math.md</a>.</p>
    </article>
  );
}
