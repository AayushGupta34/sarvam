export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "ems-access-token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* private window: the token lasts only for this session's requests */
  }
}

function headers(json: boolean): HeadersInit {
  const h: Record<string, string> = { "x-access-token": getToken() };
  if (json) h["content-type"] = "application/json";
  return h;
}

export async function api<T = any>(path: string, body?: unknown, method?: string): Promise<T> {
  const form = body instanceof FormData;
  const response = await fetch(`${API_URL}${path}`, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers: headers(body !== undefined && !form),
    body: form ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `Request failed (${response.status})`);
  }
  return response.json();
}

export const assetUrl = (path: string) => `${API_URL}${path}`;
export const feedUrl = (id: string, file: string) => `${API_URL}/api/feeds/${id}/${file}?token=${encodeURIComponent(getToken())}`;
export const wsUrl = (path: string) => `${API_URL.replace(/^http/, "ws")}${path}?token=${encodeURIComponent(getToken())}`;
