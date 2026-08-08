// 欢迎介绍页（/welcome）只在首次进入时展示；标记与用户无关、登出不清除。
export const INTRO_SEEN_KEY = "career_rag_intro_seen_v1";

// B1：模块级内存旗标兜底——localStorage 写失败（老 Safari 私密模式、企业
// 锁存储）时本次会话内仍视为已读，杜绝 `/`↔`/welcome` 重定向死循环。
let seenInMemory = false;

export function hasSeenIntro(): boolean {
  if (seenInMemory) return true;
  try {
    return localStorage.getItem(INTRO_SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function markIntroSeen(): void {
  seenInMemory = true;
  try {
    localStorage.setItem(INTRO_SEEN_KEY, "1");
  } catch {
    // 隐私模式等场景写入失败：内存旗标兜住本次会话；下次进入再看一遍介绍
  }
}

export function resetIntroSeenForTests(): void {
  seenInMemory = false;
}
