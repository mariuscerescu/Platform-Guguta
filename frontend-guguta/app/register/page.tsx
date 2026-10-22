"use client";

import { useMemo } from "react";
import AuthConversation, { type TalkStep, type TalkValues } from "../components/AuthConversation";
import { ApiError, registerPassword } from "../../lib/api";
import { withBase } from "../../lib/paths";

const CLASSES = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
/** Clasele pentru care Guguță cere confirmarea unui părinte sau tutore (vezi API, PARENT_CONSENT_CLASSES). */
const PARENT_CLASSES = new Set(CLASSES.slice(0, 8));
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export default function RegisterPage() {
  const steps = useMemo<TalkStep[]>(() => [
    {
      id: "firstName", kind: "text", field: { label: "Prenume" }, autoComplete: "given-name", placeholder: "Prenumele tău",
      ask: () => "Cum te cheamă? Spune-mi prenumele tău.",
      validate: (v) => (v.length < 2 ? "Prenumele pare prea scurt." : null),
      after: (v) => `Încântat, ${v}!`,
    },
    {
      id: "lastName", kind: "text", field: { label: "Nume" }, autoComplete: "family-name", placeholder: "Numele de familie",
      ask: () => "Și numele de familie?",
      validate: (v) => (v.length < 2 ? "Numele pare prea scurt." : null),
    },
    {
      id: "school", kind: "text", field: { label: "Școala" }, autoComplete: "organization", placeholder: "ex. Liceul Teoretic „Ion Creangă”, Bălți",
      ask: () => "La ce școală înveți? Scrie numele școlii și localitatea.",
      validate: (v) => (v.length < 3 ? "Scrie numele complet al școlii." : null),
    },
    {
      id: "classLevel", kind: "choice", field: { label: "Clasa", format: (v) => `a ${v}-a` },
      options: CLASSES.map((c) => ({ value: c, label: c })),
      ask: () => "În ce clasă ești? Alege de mai jos.",
      after: (v) => (PARENT_CLASSES.has(v) ? "Super! Pentru clasa ta am nevoie și de acordul unui părinte, îl întreb imediat." : "Super!"),
    },
    {
      id: "email", kind: "email", field: { label: "E-mail" }, autoComplete: "email", placeholder: "nume@exemplu.md",
      ask: () => "Care este adresa ta de e-mail? Cu ea intri în cont data viitoare.",
      validate: (v) => (EMAIL.test(v) ? null : "Adresa de e-mail nu arată bine. Verifică @ și domeniul."),
    },
    {
      id: "parentConsent", kind: "confirm", field: { label: "Acordul părintelui" },
      skip: (values) => !PARENT_CLASSES.has(values.classLevel ?? ""),
      ask: () => "Un părinte sau un tutore: te rog preia tastatura, citește politica de confidențialitate și confirmă personal dacă ești de acord să-i creezi contul copilului.",
      extra: () => <p className="muted">Confirmarea se înregistrează, dar formularul nu verifică separat identitatea adultului. Pentru clasele I–VIII, acest pas rămâne o măsură provizorie până configurăm autorizarea și verificarea părintelui.</p>,
      confirmLabel: "Da, este de acord", declineLabel: "Nu încă",
      declineSay: "Nicio problemă. Roagă un părinte sau un tutore să citească politica de confidențialitate împreună cu tine și revenim când e de acord.",
    },
    {
      id: "privacy", kind: "confirm", field: { label: "Confidențialitate" },
      ask: () => "Ca să-ți păstrez carnetele, am nevoie de numele, școala, clasa și e-mailul tău. Le folosesc doar pentru platformă și nu le dau mai departe fără acordul tău. Ești de acord?",
      extra: () => (
        <p className="muted">
          Citește <a href={withBase("/confidentialitate")} target="_blank" rel="noopener">Politica de confidențialitate</a> și{" "}
          <a href={withBase("/termeni")} target="_blank" rel="noopener">Termenii de utilizare</a>. Îți poți vedea, corecta sau șterge datele oricând din „Contul meu”.
        </p>
      ),
      confirmLabel: "Sunt de acord", declineLabel: "Vreau să citesc întâi",
      declineSay: "Sigur. Deschide politica din linkul de mai sus și, când ești gata, apasă „Sunt de acord”.",
    },
    {
      id: "review", kind: "review", reviewOf: ["firstName", "lastName", "school", "classLevel", "email"],
      ask: () => "Verifică, te rog: nu am introdus nicio greșeală?",
      confirmLabel: "Totul e corect",
    },
    {
      id: "password", kind: "password", field: { label: "Parola", mask: true }, autoComplete: "new-password", placeholder: "Minimum 8 caractere",
      ask: () => "Acum scrie parola ta. Ea este cheia de la dulapul tău virtual cu carnete: minimum 8 caractere, și nu o spune nimănui, nici mie!",
      validate: (v) => (v.length < 8 ? "Parola trebuie să aibă cel puțin 8 caractere." : null),
    },
    {
      id: "passwordConfirm", kind: "password", autoComplete: "new-password", placeholder: "Repetă parola",
      ask: () => "Mai scrie-o o dată, ca să fiu sigur că ai ținut-o minte.",
      validate: (v, values) => (v !== values.password ? "Parolele nu coincid. Încearcă din nou." : null),
    },
  ], []);

  async function complete(values: TalkValues) {
    try {
      await registerPassword({
        firstName: values.firstName, lastName: values.lastName, email: values.email, password: values.password,
        school: values.school, classLevel: values.classLevel, privacyAccepted: values.privacy === "da",
        parentConsent: values.parentConsent === "da",
      });
      window.location.href = withBase("/app");
      return null;
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Nu am putut crea contul. Încearcă din nou.";
      const stepId = /email/i.test(message) ? "email" : /parol/i.test(message) ? "password" : /clas/i.test(message) ? "classLevel" : "review";
      return { error: message, stepId };
    }
  }

  return (
    <AuthConversation
      title="Hai să-ți facem cont"
      intro={["Bună! Eu sunt Guguță. Îți pregătesc dulapul cu carnete, dar mai întâi te cunosc puțin."]}
      steps={steps}
      sheetTitle="Fișa ta"
      submitLabel="Contul este creat. Te duc la carnete…"
      onComplete={complete}
      footer={<p className="auth-switch">Ai deja cont? <a href={withBase("/login")}>Intră în cont</a></p>}
    />
  );
}
