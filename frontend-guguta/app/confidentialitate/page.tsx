import type { Metadata } from "next";
import { withBase } from "../../lib/paths";

export const metadata: Metadata = { title: "Politica de confidențialitate · Guguță" };

/** Versiunea afișată trebuie să coincidă cu PRIVACY_POLICY_VERSION din API. */
const PRIVACY_VERSION = "2026-10-22";

export default function PrivacyPage() {
  return (
    <article className="legal">
      <h1>Politica de confidențialitate</h1>
      <p className="muted">Versiunea {PRIVACY_VERSION}. Informare de lucru pentru proiectul de cercetare; trebuie validată de instituția responsabilă pentru prelucrarea datelor înainte de utilizarea cu elevi (decizia D-07).</p>

      <h2>1. Cine prelucrează datele</h2>
      <p>Platforma educațională Guguță este dezvoltată în cadrul proiectului de cercetare „Platformă Educațională bazată pe Inteligența Artificială «Guguță»” (programul Tineri Cercetători, cifrul 25.80012.0807.21TC, 2025–2026), implementat de Universitatea de Stat din Moldova împreună cu Institutul de Matematică și Informatică „Vladimir Andrunachievici”. Operatorul de date este echipa proiectului; contact: <a href="mailto:tudor.bumbu@math.md">tudor.bumbu@math.md</a>.</p>
      <p>Prelucrăm datele conform Legii nr. 195/2024 privind protecția datelor cu caracter personal, în vigoare din 23 august 2026, care transpune Regulamentul (UE) 2016/679 (GDPR). Aplicăm principiile de minimizare, transparență și securitate.</p>

      <h2>2. Ce date colectăm și de ce</h2>
      <table>
        <thead><tr><th>Date</th><th>Scop</th><th>Temei</th></tr></thead>
        <tbody>
          <tr><td>Prenume, nume, e-mail, parolă (stocată doar ca hash)</td><td>Crearea contului și autentificarea</td><td>Executarea contractului de utilizare (contul tău)</td></tr>
          <tr><td>Școala și clasa</td><td>Adaptarea materialelor, a tutorelui și a interfeței la nivelul tău</td><td>Consimțământ, exprimat la înregistrare</td></tr>
          <tr><td>Materialele încărcate, carnetele, notițele, conversațiile cu Guguță, răspunsurile la quizuri</td><td>Funcționarea platformei: răspunsuri cu surse, exerciții, progres</td><td>Executarea contractului</td></tr>
          <tr><td>Audio și transcriere (doar când pornești dictarea sau conversația vocală)</td><td>Dictare, căutare în materiale și conversație vocală</td><td>Inițierea voluntară a funcției; detalii despre furnizori mai jos</td></tr>
          <tr><td>Jurnale tehnice (ora cererii, identificator de cerere, erori)</td><td>Securitate și depanare</td><td>Interes legitim</td></tr>
        </tbody>
      </table>
      <p>Nu colectăm date biometrice, localizare, date despre sănătate și nu afișăm publicitate.</p>

      <h2>3. Minori</h2>
      <p>Platforma se adresează elevilor. Conform art. 8 din Legea nr. 195/2024, atunci când prelucrarea se bazează pe consimțământ pentru un serviciu online oferit direct copilului, sub 14 ani este necesară autorizarea reprezentantului legal. Formularul actual folosește provizoriu clasa ca reper și înregistrează o confirmare introdusă în timpul înscrierii; acesta nu verifică separat identitatea părintelui. Fluxul de verificare a autorizării este în curs de completare și trebuie validat de instituția responsabilă înainte de folosirea cu minori. Părintele sau tutorele poate cere accesul la datele copilului, corectarea sau ștergerea lor la adresa de contact de mai sus.</p>

      <h2>4. Cine mai vede datele (împuterniciți)</h2>
      <ul>
        <li><strong>OpenRouter și furnizorul modelului selectat</strong>: când OpenRouter este configurat pentru funcțiile AI, primesc întrebarea și fragmentele de materiale necesare procesării. Aplicația cere rutare cu setările Zero Data Retention și fără colectare de date; acestea nu elimină posibilitatea procesării temporare și depind de politica furnizorului selectat. Evită să incluzi date personale în materiale sau întrebări dacă nu sunt necesare.</li>
        <li><strong>Google Gemini API</strong>: când Gemini este furnizorul configurat pentru chat și generarea resurselor, Google primește întrebările, istoricul necesar, fragmentele autorizate și imaginile relevante din materiale. Integrarea trimite cererile direct la Google. Utilizarea și retenția datelor depind de nivelul și condițiile proiectului Google configurat; abonamentul plătit standard declară că datele nu sunt folosite pentru îmbunătățirea produselor, fără a reprezenta o garanție de retenție zero.</li>
        <li><strong>Dictare (Parakeet-ASR)</strong>: când apeși dictarea și înregistrezi, fișierul audio este trimis de platformă la serviciul privat de transcriere al proiectului, iar textul recunoscut este returnat în câmpul de mesaj.</li>
        <li><strong>Conversație vocală ElevenLabs</strong>: când pornești conversația vocală, fluxul audio al microfonului și replicile transcrise sunt procesate de ElevenLabs. Pentru carnetele deschise, platforma trimite și contextul educațional sau fragmentele necesare răspunsului. Conversația se oprește când închizi sesiunea.</li>
        <li><strong>Conversație vocală OpenAI GPT-Live</strong>: dacă această opțiune este activată și selectată, fluxul audio și contextul educațional al carnetului sunt transmise către OpenAI pentru conversația în timp real.</li>
        <li><strong>PlayQuiz (play-quiz.com)</strong>: doar dacă apeși „Deschide în PlayQuiz” și îți dai acordul; atunci trimitem numele afișat, e-mailul și întrebările quizului, ca să ți se creeze contul acolo.</li>
      </ul>
      <p>Platforma poate transmite date furnizorilor externi enumerați mai sus. Unii furnizori pot prelucra date în afara Republicii Moldova; locația, retenția și garanțiile aplicabile depind de furnizor și de configurația activă a serviciului. Nu vindem datele în scopuri comerciale. Înainte de pilot, instituția responsabilă trebuie să valideze furnizorii, acordurile de prelucrare și condițiile transferurilor internaționale.</p>

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
      <p>Datele contului și conținutul tău rămân cât timp contul există. La ștergerea contului, carnetele, materialele, conversațiile, credențialele și sesiunile se șterg; rămâne un rând fără nume, e-mail, școală sau clasă, necesar integrității înregistrărilor legate de contul șters. Durata de păstrare a jurnalelor tehnice trebuie confirmată de instituția responsabilă.</p>

      <h2>7. Drepturile tale</h2>
      <ul>
        <li><strong>Acces și rectificare</strong>: în pagina <a href={withBase("/cont")}>Contul meu</a> vezi și corectezi numele, școala și clasa.</li>
        <li><strong>Ștergere</strong>: tot din „Contul meu”, butonul „Șterge contul”; efectul este imediat.</li>
        <li><strong>Portabilitate, opoziție, restricționare</strong>: scrie-ne la adresa de contact. Cererile se examinează în termenele prevăzute de lege.</li>
        <li><strong>Retragerea consimțământului</strong>: oricând, fără a afecta prelucrările anterioare.</li>
        <li><strong>Plângere</strong>: la Centrul Național pentru Protecția Datelor cu Caracter Personal al Republicii Moldova (<a href="https://datepersonale.md" rel="noopener" target="_blank">datepersonale.md</a>).</li>
      </ul>

      <h2>8. Securitate</h2>
      <p>Conexiuni criptate (HTTPS), parole stocate doar ca hash, izolarea datelor fiecărui utilizator la nivelul bazei de date (politici pe rând), fișiere private neaccesibile direct din web, chei de acces criptate. Codul platformei este public: <a href="https://github.com/mariuscerescu/Platform-Guguta" rel="noopener" target="_blank">github.com/mariuscerescu/Platform-Guguta</a>.</p>

      <h2>9. Sondajul pentru elevi</h2>
      <p><a href={withBase("/sondaj")}>Sondajul despre Guguță</a> se completează voluntar, fără cont. Răspunsurile nu sunt asociate contului, numelui, emailului sau școlii. În înregistrările sondajului păstrăm răspunsurile, versiunea întrebărilor, data completării și un cod aleatoriu pentru a evita dublarea unei trimiteri. Nu includem IP-ul, cookie-urile sau datele browserului în aceste înregistrări; jurnalele tehnice ale serverului sunt separate.</p>
      <p>Distribuțiile răspunsurilor și textele de la cele două întrebări opționale sunt <a href={withBase("/sondaj/rezultate")}>publice</a>, inclusiv în export. Nu afișăm profilul complet de răspunsuri al unui elev. Nu scrie nume, școala, contacte sau alte informații care te identifică pe tine ori pe altcineva. Răspunsurile sunt folosite pentru îmbunătățirea platformei și cercetare educațională și nu sunt trimise furnizorilor AI.</p>
      <p>Formularul netrimis se păstrează în memoria sesiunii filei browserului, pentru a putea continua după o reîncărcare. Răspunsurile din browser se elimină după confirmarea trimiterii sau la închiderea sesiunii filei. Sondajele salvate nu sunt șterse odată cu un cont, deoarece nu sunt legate de acesta.</p>

      <h2>10. Modificări</h2>
      <p>La schimbarea acestei informări, versiunea de mai sus se actualizează. Dacă se schimbă scopurile sau temeiul prelucrării, instituția responsabilă stabilește măsurile de informare și, când este necesar, obține un nou consimțământ.</p>
    </article>
  );
}
