/** Guguță API client — same-origin proxy, cookie session + CSRF header. */

const API = "/guguta-api";
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

export async function me(): Promise<{ display_name: string } | null> {
  try {
    return await api<{ display_name: string }>("GET", "/api/v1/auth/me");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null;
    throw err;
  }
}

export interface Notebook {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  origin: string;
  context_revision: number;
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
