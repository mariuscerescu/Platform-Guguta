import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Guguță — Învață cu materialele tale",
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
          <div className="wordmark">
            Guguță
            <span className="descriptor">Învață cu materialele tale</span>
          </div>
          <nav>
            <a href="/">Acasă</a>
          </nav>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
