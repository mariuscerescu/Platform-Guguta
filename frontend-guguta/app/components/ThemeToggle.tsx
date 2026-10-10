"use client";

import { useSyncExternalStore } from "react";
import { currentTheme, serverTheme, setTheme, subscribeTheme } from "../../lib/theme";

export default function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, serverTheme);
  const action = theme === "dark" ? "Activează tema luminoasă" : "Activează tema întunecată";

  return (
    <button type="button" className="theme-toggle" aria-label={action} title={action}
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {theme === "dark" ? <>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" />
        </> : <path d="M20.9 13.4A9 9 0 0 1 10.6 3.1 9 9 0 1 0 20.9 13.4Z" />}
      </svg>
    </button>
  );
}
