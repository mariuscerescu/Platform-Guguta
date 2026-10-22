import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./survey.css";

export const metadata: Metadata = {
  title: "Părerea ta despre Guguță",
  description: "20 de întrebări despre experiența elevilor cu platforma Guguță. Participare anonimă, rezultate publice.",
  referrer: "no-referrer",
};

export default function SurveyLayout({ children }: { children: ReactNode }) {
  return <div className="survey-shell">{children}</div>;
}
