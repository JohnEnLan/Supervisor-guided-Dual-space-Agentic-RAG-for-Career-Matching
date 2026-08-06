const LAST_RUN_PREFIX = "last_run:";

function key(userId: string, sessionId: string): string {
  return `${LAST_RUN_PREFIX}${userId}:${sessionId}`;
}

export function readLastRun(userId: string, sessionId: string): string | null {
  return localStorage.getItem(key(userId, sessionId));
}

export function writeLastRun(userId: string, sessionId: string, runId: string): void {
  localStorage.setItem(key(userId, sessionId), runId);
}

export function removeLastRun(userId: string, sessionId: string): void {
  localStorage.removeItem(key(userId, sessionId));
}

export function clearLastRuns(userId?: string): void {
  const prefix = userId ? `${LAST_RUN_PREFIX}${userId}:` : LAST_RUN_PREFIX;
  for (let index = localStorage.length - 1; index >= 0; index -= 1) {
    const storageKey = localStorage.key(index);
    if (storageKey?.startsWith(prefix)) localStorage.removeItem(storageKey);
  }
}
