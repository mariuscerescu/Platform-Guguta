import { withBase } from "../../lib/paths";

export default function SiteFooter() {
  return (
    <footer className="site-footer">
      <span>Platforma educațională Guguță · proiect de cercetare 25.80012.0807.21TC</span>
      <nav aria-label="Informații legale">
        <a href={withBase("/confidentialitate")}>Confidențialitate</a>
        <a href={withBase("/termeni")}>Termeni</a>
        <a href={withBase("/cont")}>Contul meu</a>
      </nav>
    </footer>
  );
}
