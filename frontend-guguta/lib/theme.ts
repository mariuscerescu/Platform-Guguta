export type Theme = "light" | "dark";

const STORAGE_KEY = "guguta_theme_v1";
const COLORS: Record<Theme, string> = { light: "#f7faff", dark: "#090d12" };
const listeners = new Set<() => void>();
let systemMedia: MediaQueryList | null = null;

function savedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function preferredTheme(): Theme {
  return savedTheme() ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.getElementById("guguta-theme-color")?.setAttribute("content", COLORS[theme]);
  listeners.forEach((listener) => listener());
}

export function setTheme(theme: Theme) {
  // The control still works when the browser does not allow persistent storage.
  try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* Session-only theme. */ }
  applyTheme(theme);
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function serverTheme(): Theme { return "dark"; }

function onStorage(event: StorageEvent) {
  try { if (event.storageArea !== localStorage) return; } catch { return; }
  if (event.key === STORAGE_KEY || event.key === null) {
    applyTheme(preferredTheme());
  }
}

function onSystemTheme() {
  if (!savedTheme()) applyTheme(preferredTheme());
}

export function subscribeTheme(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) {
    systemMedia = window.matchMedia("(prefers-color-scheme: dark)");
    window.addEventListener("storage", onStorage);
    systemMedia.addEventListener("change", onSystemTheme);
    // Keep the browser chrome in sync with the selected palette.
    applyTheme(currentTheme());
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.removeEventListener("storage", onStorage);
      systemMedia?.removeEventListener("change", onSystemTheme);
      systemMedia = null;
    }
  };
}

// Runs in the head before the page paints; React hydrates the same button markup.
export const THEME_INIT_SCRIPT = `(function(){
  var theme;
  try { theme = localStorage.getItem("${STORAGE_KEY}"); } catch (_) {}
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle("dark", theme === "dark");
  var meta = document.getElementById("guguta-theme-color");
  if (!meta) {
    meta = document.createElement("meta");
    meta.id = "guguta-theme-color";
    meta.name = "theme-color";
    document.head.appendChild(meta);
  }
  meta.content = theme === "dark" ? "${COLORS.dark}" : "${COLORS.light}";
})();`;
