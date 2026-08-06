const LAST_RUN_PREFIX = "last_run:";
const SESSION_TITLE_PREFIX = "title:";

export const SESSION_TITLE_UPDATED_EVENT = "career-rag:session-title-updated";

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

function titleKey(userId: string, sessionId: string): string {
  return `${SESSION_TITLE_PREFIX}${userId}:${sessionId}`;
}

export function readSessionTitle(userId: string, sessionId: string): string | null {
  return localStorage.getItem(titleKey(userId, sessionId));
}

export function writeSessionTitle(userId: string, sessionId: string, careerGoal: string): void {
  const title = careerGoal.trim().slice(0, 12);
  if (title) localStorage.setItem(titleKey(userId, sessionId), title);
  else localStorage.removeItem(titleKey(userId, sessionId));
  window.dispatchEvent(new Event(SESSION_TITLE_UPDATED_EVENT));
}

export function clearUserScopedStorage(userId?: string): void {
  const prefixes = userId
    ? [`${LAST_RUN_PREFIX}${userId}:`, `${SESSION_TITLE_PREFIX}${userId}:`]
    : [LAST_RUN_PREFIX, SESSION_TITLE_PREFIX];
  for (let index = localStorage.length - 1; index >= 0; index -= 1) {
    const storageKey = localStorage.key(index);
    if (storageKey && prefixes.some((prefix) => storageKey.startsWith(prefix))) {
      localStorage.removeItem(storageKey);
    }
  }
}
