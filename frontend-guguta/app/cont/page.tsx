"use client";

import { useEffect, useState } from "react";
import { deleteAccount, me, updateProfile, type MeInfo } from "../../lib/api";
import { withBase } from "../../lib/paths";

const CLASSES = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
const CONSENT_LABELS: Record<string, string> = {
  privacy: "Politica de confidențialitate",
  terms: "Termenii de utilizare",
  parent: "Acordul părintelui sau tutorelui",
};

/** Contul meu: acces, rectificare și ștergere (drepturile persoanei vizate). */
export default function AccountPage() {
  const [user, setUser] = useState<MeInfo | null | undefined>(undefined);
  const [displayName, setDisplayName] = useState("");
  const [school, setSchool] = useState("");
  const [classLevel, setClassLevel] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    void me().then((value) => {
      setUser(value);
      if (value) {
        setDisplayName(value.display_name);
        setSchool(value.school ?? "");
        setClassLevel(value.class_level ?? "");
      }
    });
  }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setSaved(false); setError(null);
    try {
      const updated = await updateProfile({ displayName: displayName.trim(), school: school.trim(), classLevel });
      setUser(updated);
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (confirmText !== "ȘTERGE") return;
    setDeleting(true); setError(null);
    try {
      await deleteAccount();
      window.location.href = withBase("/");
    } catch (err) {
      setError((err as Error).message);
      setDeleting(false);
    }
  }

  if (user === undefined) return <p className="muted account-loading">Se încarcă…</p>;
  if (user === null) {
    return (
      <section className="account">
        <h1>Contul meu</h1>
        <p>Nu ești autentificat. <a href={withBase("/login")}>Intră în cont</a> ca să-ți vezi datele.</p>
      </section>
    );
  }

  return (
    <section className="account">
      <h1>Contul meu</h1>
      <p className="muted">Aici vezi datele pe care le păstrăm despre tine, le corectezi sau ștergi contul. Detalii în <a href={withBase("/confidentialitate")}>Politica de confidențialitate</a>.</p>

      <form onSubmit={save} className="auth-form account-form">
        <label><span>Nume afișat</span><input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={255} /></label>
        <label><span>E-mail</span><input value={user.email ?? "—"} readOnly /></label>
        <label><span>Școala</span><input value={school} onChange={(e) => setSchool(e.target.value)} maxLength={200} placeholder="Numele școlii și localitatea" /></label>
        <label>
          <span>Clasa</span>
          <select value={classLevel} onChange={(e) => setClassLevel(e.target.value)}>
            <option value="">—</option>
            {CLASSES.map((c) => <option key={c} value={c}>a {c}-a</option>)}
          </select>
        </label>
        {error && <p className="error-text" role="alert">{error}</p>}
        {saved && <p className="muted" role="status">Datele au fost salvate.</p>}
        <button className="primary" disabled={saving || !displayName.trim() || !school.trim() || !classLevel}>{saving ? "Se salvează…" : "Salvează"}</button>
      </form>

      <h2>Acorduri</h2>
      {user.consents && Object.keys(user.consents).length > 0 ? (
        <ul className="account-consents">
          {Object.entries(user.consents).map(([kind, version]) => (
            <li key={kind}><span>{CONSENT_LABELS[kind] ?? kind}</span><span className="muted">versiunea {version}</span></li>
          ))}
        </ul>
      ) : <p className="muted">Contul a fost creat înainte de introducerea acordurilor explicite.</p>}

      <h2>Șterge contul</h2>
      <p>Se șterg carnetele, materialele, conversațiile și datele de autentificare. Acțiunea nu se poate anula. Scrie <strong>ȘTERGE</strong> ca să confirmi.</p>
      <div className="account-delete">
        <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder="ȘTERGE" aria-label="Confirmă ștergerea" />
        <button type="button" className="chip danger" disabled={deleting || confirmText !== "ȘTERGE"} onClick={() => void remove()}>{deleting ? "Se șterge…" : "Șterge contul"}</button>
      </div>
    </section>
  );
}
