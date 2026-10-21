import type { Metadata } from "next";
import { withBase } from "../../lib/paths";

export const metadata: Metadata = { title: "Politica de confidențialitate · Guguță" };

/** Versiunea afișată trebuie să coincidă cu PRIVACY_POLICY_VERSION din API. */
const PRIVACY_VERSION = "2026-10-21";

export default function PrivacyPage() {
  return (
    <article className="legal">
      <h1>Politica de confidențialitate</h1>
      <p className="muted">Versiunea {PRIVACY_VERSION}. Versiune de lucru a proiectului de cercetare; se validează cu responsabilul instituțional (decizia D-07 din documentația proiectului).</p>

      <h2>1. Cine prelucrează datele</h2>
      <p>Platforma educațională Guguță este dezvoltată în cadrul proiectului de cercetare „Platformă Educațională bazată pe Inteligența Artificială «Guguță»” (programul Tineri Cercetători, cifrul 25.80012.0807.21TC, 2025–2026), implementat de Universitatea de Stat din Moldova împreună cu Institutul de Matematică și Informatică „Vladimir Andrunachievici”. Operatorul de date este echipa proiectului; contact: <a href="mailto:tudor.bumbu@math.md">tudor.bumbu@math.md</a>.</p>
      <p>Prelucrăm datele conform legislației Republicii Moldova privind protecția datelor cu caracter personal, aliniată Regulamentului (UE) 2016/679 (GDPR), și principiilor de minimizare, transparență și securitate.</p>

      <h2>2. Ce date colectăm și de ce</h2>
      <table>
        <thead><tr><th>Date</th><th>Scop</th><th>Temei</th></tr></thead>
        <tbody>
          <tr><td>Prenume, nume, e-mail, parolă (stocată doar ca hash)</td><td>Crearea contului și autentificarea</td><td>Executarea contractului de utilizare (contul tău)</td></tr>
          <tr><td>Școala și clasa</td><td>Adaptarea materialelor, a tutorelui și a interfeței la nivelul tău</td><td>Consimțământ, exprimat la înregistrare</td></tr>
          <tr><td>Materialele încărcate, carnetele, notițele, conversațiile cu Guguță, răspunsurile la quizuri</td><td>Funcționarea platformei: răspunsuri cu surse, exerciții, progres</td><td>Executarea contractului</td></tr>
          <tr><td>Înregistrări vocale (doar când apeși microfonul)</td><td>Transcriere și conversație vocală</td><td>Consimțământ, la fiecare utilizare</td></tr>
          <tr><td>Jurnale tehnice (ora cererii, identificator de cerere, erori)</td><td>Securitate și depanare</td><td>Interes legitim</td></tr>
        </tbody>
      </table>
      <p>Nu colectăm date biometrice, localizare, date despre sănătate și nu afișăm publicitate.</p>

      <h2>3. Minori</h2>
      <p>Platforma se adresează elevilor. Pentru elevii din clasele I–VIII cerem, la înregistrare, confirmarea că un părinte sau tutore știe și este de acord. Părintele sau tutorele poate cere oricând accesul la datele copilului, corectarea sau ștergerea lor, la adresa de contact de mai sus.</p>

      <h2>4. Cine mai vede datele (împuterniciți)</h2>
      <ul>
        <li><strong>Furnizorul de modele de limbaj</strong> (OpenRouter, cu rutare către furnizori care nu rețin și nu antrenează pe date): primește fragmentele din materiale și întrebările necesare răspunsului, fără numele sau e-mailul tău.</li>
        <li><strong>Transcriere și sinteză vocală</strong>: rulează pe serverele proiectului; dacă este configurat un furnizor extern de voce, acesta primește doar textul replicii.</li>
        <li><strong>PlayQuiz (play-quiz.com)</strong>: doar dacă apeși „Deschide în PlayQuiz” și îți dai acordul; atunci trimitem numele afișat, e-mailul și întrebările quizului, ca să ți se creeze contul acolo.</li>
      </ul>
      <p>Serverele platformei se află în Republica Moldova. Nu vindem și nu cedăm date terților în scopuri comerciale.</p>

      <h2>5. Cookie-uri și stocare locală</h2>
      <table>
        <thead><tr><th>Nume</th><th>Tip</th><th>Rol</th><th>Durată</th></tr></thead>
        <tbody>
          <tr><td><code>guguta_session</code></td><td>cookie strict necesar</td><td>sesiunea ta autentificată</td><td>până la 12 ore sau delogare</td></tr>
          <tr><td><code>guguta_oidc_state</code></td><td>cookie strict necesar</td><td>protecția autentificării instituționale</td><td>câteva minute, în timpul autentificării</td></tr>
          <tr><td><code>guguta_csrf</code>, tema, poziția mascotei, informarea despre cookie-uri</td><td>stocare locală în browser</td><td>protecția formularelor și preferințe de afișare</td><td>până le ștergi din browser</td></tr>
        </tbody>
      </table>
      <p>Nu folosim cookie-uri de urmărire, analitice sau de publicitate, de aceea nu există un mecanism de refuz: informarea se afișează o singură dată.</p>

      <h2>6. Cât timp păstrăm datele</h2>
      <p>Datele contului și conținutul tău rămân cât timp contul există. La ștergerea contului, carnetele, materialele, conversațiile, credențialele și sesiunile se șterg; rămâne doar un rând anonimizat (fără nume, e-mail, școală sau clasă), necesar integrității jurnalelor. Jurnalele tehnice se păstrează cel mult 12 luni.</p>

      <h2>7. Drepturile tale</h2>
      <ul>
        <li><strong>Acces și rectificare</strong>: în pagina <a href={withBase("/cont")}>Contul meu</a> vezi și corectezi numele, școala și clasa.</li>
        <li><strong>Ștergere</strong>: tot din „Contul meu”, butonul „Șterge contul”; efectul este imediat.</li>
        <li><strong>Portabilitate, opoziție, restricționare</strong>: scrie-ne la adresa de contact; răspundem în cel mult 30 de zile.</li>
        <li><strong>Retragerea consimțământului</strong>: oricând, fără a afecta prelucrările anterioare.</li>
        <li><strong>Plângere</strong>: la Centrul Național pentru Protecția Datelor cu Caracter Personal al Republicii Moldova (<a href="https://datepersonale.md" rel="noopener" target="_blank">datepersonale.md</a>).</li>
      </ul>

      <h2>8. Securitate</h2>
      <p>Conexiuni criptate (HTTPS), parole stocate doar ca hash, izolarea datelor fiecărui utilizator la nivelul bazei de date (politici pe rând), fișiere private neaccesibile direct din web, chei de acces criptate. Codul platformei este public: <a href="https://github.com/mariuscerescu/Platform-Guguta" rel="noopener" target="_blank">github.com/mariuscerescu/Platform-Guguta</a>.</p>

      <h2>9. Modificări</h2>
      <p>La schimbarea acestei politici, versiunea de mai sus se actualizează și, dacă schimbarea afectează datele tale, Guguță îți cere din nou acordul la următoarea intrare în cont.</p>
    </article>
  );
}
