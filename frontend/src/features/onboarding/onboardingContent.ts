export type ChapterKind =
  | "prologue"
  | "fog"
  | "coordinates"
  | "direction"
  | "fleet"
  | "navigation"
  | "departure";

export type MissionChapter = {
  id: ChapterKind;
  number: string;
  eyebrow: string;
  title: string;
  body: string;
  coordinate: string;
};

export const EXPEDITION_CHAPTERS: readonly MissionChapter[] = [
  {
    id: "prologue",
    number: "01",
    eyebrow: "THE CAREER EXPEDITION",
    title: "职业不是一次匹配，而是一条航线",
    body: "我们不替你决定未来。我们从真实经历出发，让每一次选择都有坐标、有边界、有证据。",
    coordinate: "ORIGIN · YOUR EVIDENCE",
  },
  {
    id: "fog",
    number: "02",
    eyebrow: "BEYOND SIMILARITY",
    title: "相似，不等于适合",
    body: "关键词相近只能发现可能的道路；地点、签证、经验、岗位状态与真实证据，才决定道路是否能够抵达。",
    coordinate: "FILTER · VERIFY · THEN RANK",
  },
  {
    id: "coordinates",
    number: "03",
    eyebrow: "RESUME CONSTELLATION",
    title: "从已经发生的经历出发",
    body: "技能、项目、教育与经历被保留为可追溯的原文证据。没有真实坐标，就不生成虚构的路线。",
    coordinate: "SKILL · PROJECT · EDUCATION · EXPERIENCE",
  },
  {
    id: "direction",
    number: "04",
    eyebrow: "INTENT CALIBRATION",
    title: "有目标，就校准；没有目标，就探索",
    body: "已有目标岗位或目标公司时，Intent Agent 锁定方向；仍在探索时，它先给出不超过三个可理解的职业方向。",
    coordinate: "目标岗位 · 目标公司 · 探索未知",
  },
  {
    id: "fleet",
    number: "05",
    eyebrow: "SUPERVISOR-GUIDED FLEET",
    title: "三位 Agent，各守一段航程",
    body: "Intent 理解方向，Matching 检索证据，Strategy 规划行动，Supervisor 核查约束，并把恢复限制在有界循环内。",
    coordinate: "Intent · Matching · Strategy · Supervisor",
  },
  {
    id: "navigation",
    number: "06",
    eyebrow: "DUAL-SPACE NAVIGATION",
    title: "两种信号，共同校准一条路线",
    body: "显式岗位空间提供 JD evidence，匿名案例空间只重排已有候选；任何信号都不能穿过硬约束安全门。",
    coordinate: "显式岗位空间 · 匿名案例空间 · HARD GATE",
  },
  {
    id: "departure",
    number: "07",
    eyebrow: "EVIDENCE OATH",
    title: "未来不由模型决定，但每一步都应有证据",
    body: "公开结果不返回完整简历、内部提示词、供应商错误或 API Key。方向属于你，证据负责照亮道路。",
    coordinate: "READY FOR DEPARTURE",
  },
] as const;
