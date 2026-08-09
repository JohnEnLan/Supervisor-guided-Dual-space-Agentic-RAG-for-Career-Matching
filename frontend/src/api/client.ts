const API_PREFIX = "/api/v1";

type ErrorDetail = {
  message?: unknown;
  recovery?: unknown;
  error_code?: unknown;
};

export type RecoveryHint = {
  action?: string;
  status_url?: string;
};

export class ApiError extends Error {
  readonly status: number;
  readonly recovery?: RecoveryHint;
  readonly errorCode?: string;

  constructor(status: number, message: string, recovery?: RecoveryHint, errorCode?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.recovery = recovery;
    this.errorCode = errorCode;
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

function recoveryOrUndefined(value: unknown): RecoveryHint | undefined {
  if (!isRecord(value)) return undefined;
  const action = textOrUndefined(value.action);
  const statusUrl = textOrUndefined(value.status_url);
  return action || statusUrl ? { action, status_url: statusUrl } : undefined;
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
    recoveryOrUndefined(detail.recovery),
    textOrUndefined(detail.error_code),
  );
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");

  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const error = await toApiError(response);
    if (response.status === 401) {
      notifyUnauthorized(error);
    }
    throw error;
  }
  // 204（如 logout）无响应体，response.json() 会抛 SyntaxError
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

type UnauthorizedListener = (error: ApiError) => void;

let unauthorizedListener: UnauthorizedListener | null = null;

/** 全局 401 监听：AppShell 注册后，任何请求 401 都会统一跳回登录。 */
export function onUnauthorized(listener: UnauthorizedListener | null): void {
  unauthorizedListener = listener;
}

function notifyUnauthorized(error: ApiError): void {
  unauthorizedListener?.(error);
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
