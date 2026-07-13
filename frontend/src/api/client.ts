const API_PREFIX = "/api/v1";

type ErrorDetail = {
  message?: unknown;
  recovery?: unknown;
};

export class ApiError extends Error {
  readonly status: number;
  readonly recovery?: string;

  constructor(status: number, message: string, recovery?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.recovery = recovery;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function projectErrorDetail(value: unknown): ErrorDetail {
  if (!isRecord(value)) {
    return {};
  }
  const detail = value.detail;
  if (typeof detail === "string") {
    return { message: detail };
  }
  return isRecord(detail) ? detail : {};
}

function textOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  const detail = projectErrorDetail(body);
  return new ApiError(
    response.status,
    textOrUndefined(detail.message) ?? `Request failed with status ${response.status}.`,
    textOrUndefined(detail.recovery),
  );
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");

  const response = await fetch(`${API_PREFIX}${path}`, { ...init, headers });
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

export function jsonRequest<TRequest, TResponse>(
  path: string,
  method: "POST" | "PUT" | "PATCH",
  body: TRequest,
): Promise<TResponse> {
  return apiRequest<TResponse>(path, {
    method,
    body: JSON.stringify(body),
  });
}

export function uploadRequest<TResponse>(path: string, file: File): Promise<TResponse> {
  const body = new FormData();
  body.set("file", file);
  return apiRequest<TResponse>(path, { method: "POST", body });
}
