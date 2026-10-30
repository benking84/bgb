export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

function token(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("bgb.token") ?? "";
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const bearer = token();
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, `Cannot reach the backup service at ${API_BASE || "this origin"}.`);
  }
  if (!response.ok) {
    let message = response.statusText || "request failed";
    try {
      const body = await response.json();
      if (body?.error) message = body.error;
    } catch {
      /* non-json error */
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json() as Promise<T>;
  return undefined as T;
}

export async function downloadContent(url: string, filename: string) {
  const headers = new Headers();
  const bearer = token();
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);
  const response = await fetch(`${API_BASE}${url}`, { headers });
  if (!response.ok) {
    throw new ApiError(response.status, "Could not restore that file");
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}
