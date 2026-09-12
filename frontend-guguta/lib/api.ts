/** Guguță API client — same-origin proxy, cookie session + CSRF header. */

import { API_BASE } from "./paths";

const API = API_BASE;
const CSRF_KEY = "guguta_csrf";

export function setCsrf(token: string) {
  localStorage.setItem(CSRF_KEY, token);
}

export function getCsrf(): string | null {
  return localStorage.getItem(CSRF_KEY);
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

type Json = Record<string, unknown>;

export async function api<T = Json>(
  method: string,
  path: string,
  body?: Json | unknown[],
): Promise<T> {
  const headers: Record<string, string> = {};
  const csrf = getCsrf();
  if (csrf) headers["X-Guguta-CSRF"] = csrf;
  let payload: string | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: payload,
    credentials: "same-origin",
  });
  const data = (await res.json().catch(() => ({}))) as T & {
    code?: string;
    message?: string;
    detail?: string;
  };
  if (!res.ok) {
    throw new ApiError(
      res.status,
      data.code ?? "error",
      data.message ?? data.detail ?? "Eroare neașteptată.",
    );
  }
  return data;
}



function serverAuthErrorMessage(status: number, fallback: string): string {
  if (status >= 500) {
    return "Serverul de autentificare nu răspunde. Pornește backend-ul și aplică migrarea bazei de date.";
  }
  return fallback;
}

export async function loginPassword(email: string, password: string): Promise<void> {
  const res = await fetch(`${API}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { message?: string; detail?: string };
    throw new ApiError(
      res.status,
      "auth_failed",
      data.message ?? data.detail ?? serverAuthErrorMessage(res.status, "Autentificare eșuată."),
    );
  }
  const csrf = res.headers.get("X-Guguta-CSRF");
  if (csrf) setCsrf(csrf);
}

export async function registerPassword(
  firstName: string,
  lastName: string,
  email: string,
  password: string,
): Promise<void> {
  const res = await fetch(`${API}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({
      first_name: firstName,
      last_name: lastName,
      email,
      password,
    }),
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { message?: string; detail?: string };
    throw new ApiError(
      res.status,
      "registration_failed",
      data.message ?? data.detail ?? serverAuthErrorMessage(res.status, "Înregistrarea a eșuat."),
    );
  }
  const csrf = res.headers.get("X-Guguta-CSRF");
  if (csrf) setCsrf(csrf);
}

export async function loginDev(displayName: string): Promise<void> {
  const res = await fetch(`${API}/api/v1/auth/dev-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { message?: string };
    throw new ApiError(res.status, "error", data.message ?? "Autentificare eșuată.");
  }
  const csrf = res.headers.get("X-Guguta-CSRF");
  if (csrf) setCsrf(csrf);
}

/** F02: session is determined by an authenticated endpoint, never by
 * localStorage. The CSRF token is bootstrapped from the same session. */
export async function me(): Promise<{ display_name: string } | null> {
  try {
    const r = await fetch(`${API}/api/v1/auth/me`, {
      credentials: "same-origin",
    });
    if (r.status === 401) return null;
    if (!r.ok) return null;
    const data = (await r.json()) as { display_name: string };
    if (!getCsrf()) await bootstrapCsrf();
    return data;
  } catch {
    return null;
  }
}

export async function bootstrapCsrf(): Promise<void> {
  const r = await fetch(`${API}/api/v1/auth/csrf`, {
    credentials: "same-origin",
  });
  if (r.ok) {
    const data = (await r.json()) as { csrf: string };
    setCsrf(data.csrf);
  }
}

export async function authMode(): Promise<string> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 1800);
  try {
    const r = await fetch(`${API}/api/v1/auth/config`, { signal: controller.signal });
    if (r.ok) return ((await r.json()) as { auth_mode: string }).auth_mode;
  } catch { }
  finally {
    window.clearTimeout(timeout);
  }
  return "password";
}

export interface Notebook {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  origin: string;
  context_revision: number;
  created_at?: string;
  source_count?: number;
}

export interface Source {
  id: string;
  local_name: string;
  status: string;
  status_detail?: string | null;
  selected_for_chat: boolean;
  material_version_id: string;
}

export interface CatalogTemplate {
  id: string;
  slug: string;
  title: string;
  description?: string | null;
  class_level?: string | null;
  discipline?: string | null;
  current_version?: number | null;
  material_count: number;
}

export interface ChatMessage {
  id: string;
  seq: number;
  role: string;
  content: string;
  context_revision: number;
  model?: string | null;
}

export interface Note {
  id: string;
  title: string;
  content: string;
  source_message_id?: string | null;
}
