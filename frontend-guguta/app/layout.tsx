import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Guguță — Carnete digitale",
  description:
    "Platforma Guguță: carnete digitale pentru elevii Republicii Moldova.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ro-MD">
      <body>
        <header className="header">
          <span className="wordmark">Guguță</span>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
