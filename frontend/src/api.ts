// Appels à l'API FastAPI. Le cookie de session est envoyé automatiquement (même origine).

export type User = {
  id: string;
  username: string;
  display_name: string;
  role: "user" | "super_admin";
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, data));
  return data as T;
}

function errorMessage(status: number, data: unknown): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (status === 422) return "Certains champs ne sont pas valides.";
  return "Une erreur est survenue. Réessaie dans un instant.";
}

export const api = {
  me: () => request<User>("GET", "/api/auth/me"),
  login: (username: string, password: string) => request<User>("POST", "/api/auth/login", { username, password }),
  register: (username: string, display_name: string, password: string) =>
    request<User>("POST", "/api/auth/register", { username, display_name, password }),
  logout: () => request<void>("POST", "/api/auth/logout"),
};
