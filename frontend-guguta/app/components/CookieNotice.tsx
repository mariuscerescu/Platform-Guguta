"use client";

import { useEffect, useState } from "react";
import { withBase } from "../../lib/paths";

const KEY = "guguta.cookie-notice.v1";

/**
 * Informare despre cookie-uri. Platforma folosește doar cookie-uri strict
 * necesare (sesiunea, starea autentificării OIDC) și stocare locală pentru
 * preferințe, deci nu există nimic de refuzat; informarea se confirmă o dată.
 */
export default function CookieNotice() {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    try { setVisible(localStorage.getItem(KEY) !== "seen"); } catch { setVisible(true); }
  }, []);
  if (!visible) return null;
  function dismiss() {
    try { localStorage.setItem(KEY, "seen"); } catch { /* fără stocare, informarea reapare */ }
    setVisible(false);
  }
  return (
    <div className="cookie-notice" role="region" aria-label="Informare despre cookie-uri">
      <p>
        Guguță folosește cookie-uri <strong>strict necesare</strong> pentru sesiunea ta. Tema, poziția mascotei și protecția formularelor folosesc stocare locală în browser.
        Nu folosim cookie-uri de urmărire sau de publicitate. Detalii în{" "}
        <a href={withBase("/confidentialitate")}>Politica de confidențialitate</a>.
      </p>
      <button type="button" className="primary" onClick={dismiss}>Am înțeles</button>
    </div>
  );
}
