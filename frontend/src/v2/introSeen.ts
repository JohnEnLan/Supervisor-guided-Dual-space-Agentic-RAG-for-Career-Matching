// 欢迎介绍页（/welcome）只在首次进入时展示；标记与用户无关、登出不清除。
export const INTRO_SEEN_KEY = "career_rag_intro_seen_v1";

export function hasSeenIntro(): boolean {
  try {
    return localStorage.getItem(INTRO_SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function markIntroSeen(): void {
  try {
    localStorage.setItem(INTRO_SEEN_KEY, "1");
  } catch {
    // 隐私模式等场景写入失败：下次进入会再看一遍介绍，可接受
  }
}
