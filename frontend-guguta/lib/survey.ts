import { API_BASE } from "./paths";

export interface SurveyQuestion {
  id: string; number: number; title: string; section: string;
  type: "single" | "rating" | "multiple" | "text";
  required: boolean; max_choices?: number; max_length?: number; exclusive?: string[];
  options: { value: string; label: string; count?: number }[];
  mean?: number | null; rated_count?: number | null; written_count?: number;
}
export interface Questionnaire { version: string; title: string; questions: SurveyQuestion[] }
export interface SurveyResults { version: string; total: number; questions: SurveyQuestion[] }
export interface SurveySession { submission_id: string; token: string }
export type SurveyAnswers = Record<string, string | string[]>;

/** Survey requests never include account cookies, CSRF/account IDs or analytics. */
export async function surveyRequest<T>(path = "", body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1/survey${path}`, {
    method: body === undefined ? "GET" : "POST",
    credentials: "omit", cache: "no-store", referrerPolicy: "no-referrer",
    headers: body === undefined ? {} : { "Content-Type": "application/json", "X-Guguta-Survey": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(25_000),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.message === "string" ? data.message : "Nu am putut salva sau încărca datele. Încearcă din nou.");
  return data as T;
}

export function answerLabel(question: SurveyQuestion, value: string | string[] | undefined): string {
  if (question.type === "text") return typeof value === "string" && value.trim() ? value : "Fără răspuns (opțional)";
  const selected = Array.isArray(value) ? value : [value];
  return question.options.filter(option => selected.includes(option.value)).map(option => option.label).join("; ");
}

export function hasAnswer(question: SurveyQuestion, value: string | string[] | undefined): boolean {
  return !question.required || (Array.isArray(value) ? value.length > 0 : Boolean(value));
}
