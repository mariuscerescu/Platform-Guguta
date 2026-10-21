import AuthEntryLink from "./components/AuthEntryLink";
import EducationCompanion from "./components/EducationCompanion";
import { withBase } from "../lib/paths";

export default function LandingPage() {
  return (
    <>
    <section className="landing-card" aria-label="Platforma educațională Guguță">
      <div className="landing-hero">
        <div className="hero-copy">
          <p>
            Carnete digitale care te ajută să înțelegi mai ușor, să pui
            întrebări și să înveți din propriile tale materiale școlare, cu
            ajutorul inteligenței artificiale.
          </p>
          <div className="hero-actions">
            <AuthEntryLink className="primary-action">Accesează materialele din platformă</AuthEntryLink>
          </div>
          <div className="hero-benefits" aria-label="Avantaje">
            <div className="benefit">
              <span className="benefit-icon image-icon"><img src={withBase("/assets/benefit-materials.png")} alt="" /></span>
              <strong>Materialele tale<br />într-un singur loc</strong>
            </div>
            <div className="benefit">
              <span className="benefit-icon image-icon"><img src={withBase("/assets/benefit-answers.png")} alt="" /></span>
              <strong>Răspunsuri clare<br />și cu surse</strong>
            </div>
            <div className="benefit">
              <span className="benefit-icon image-icon"><img src={withBase("/assets/benefit-moldova.png")} alt="" /></span>
              <strong>Creat special<br />pentru elevii din Moldova</strong>
            </div>
          </div>

          <figure className="landing-quote">
            <blockquote>
              „Cine învață astăzi<br />
              construiește Moldova de mâine.”
            </blockquote>
            <figcaption>Guguță — alături de fiecare elev</figcaption>
          </figure>
        </div>

        <div className="hero-image-wrap" aria-hidden="true">
          <div className="hand-note">
            <img src={withBase("/assets/hand-note-complete.png")} alt="" />
          </div>
          <img
            src={withBase("/assets/guguta-hero-student.png")}
            alt=""
            className="hero-student"
          />
        </div>
      </div>

      <div className="landing-stats" aria-label="Repere">
        <div>
          <span>Pentru elevi din toate clasele</span>
          <strong>5-12</strong>
        </div>
        <div>
          <span>Curriculum național</span>
          <strong className="flag-mark" aria-label="Republica Moldova">
            <img src={withBase("/assets/flag-moldova.svg")} alt="" />
          </strong>
        </div>
        <div>
          <span>Materiale în limba română</span>
          <strong className="stat-image book-stack" aria-hidden="true">
            <img src={withBase("/assets/book-stack.png")} alt="" />
          </strong>
        </div>
        <div>
          <span>Învățare mai ușoară<br />o zi mai bună</span>
          <strong className="stat-image plant-icon" aria-hidden="true">
            <img src={withBase("/assets/plant.png")} alt="" />
          </strong>
        </div>
      </div>
    </section>
    <div className="landing-companion">
      <EducationCompanion
        compact
        positionKey="landing"
        assetBase={withBase("/guguta-companion")}
        context={{ source: "opennotebook", locale: "ro-MD" }}
        activity="Bine ai venit! Eu sunt Guguță,"
        idleStatus="mereu alături de tine :)"
      />
    </div>
    </>
  );
}
