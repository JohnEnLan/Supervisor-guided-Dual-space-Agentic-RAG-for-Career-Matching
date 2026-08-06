import type { ConsultState } from "../api/queries";

export type ConsultSlotState = {
  id: "goal" | "location" | "visa";
  label: string;
  complete: boolean;
  prompt: string;
};

export function deriveConsultSlots(
  profile: ConsultState["profile_draft"] | undefined,
): ConsultSlotState[] {
  const hardConstraints = profile?.hard_constraints ?? {};
  const goal = profile?.current_goal?.find((value) => value.trim());
  const rawLocations = hardConstraints.locations;
  const locations = Array.isArray(rawLocations)
    && rawLocations.length > 0
    && rawLocations.every((value) => typeof value === "string" && Boolean(value.trim()))
    ? rawLocations.map((value) => value.trim())
    : [];
  const remote = hardConstraints.remote === true;
  const visa = hardConstraints.need_visa_sponsor;
  const visaAnswered = typeof visa === "boolean";

  return [
    {
      id: "goal",
      complete: Boolean(goal),
      label: goal ? `目标：${goal.trim()}` : "目标：待补充",
      prompt: "我的求职目标是：",
    },
    {
      id: "location",
      complete: remote || locations.length > 0,
      label: remote ? "地点：远程" : locations.length ? `地点：${locations.join(" / ")}` : "地点：待补充",
      prompt: "我希望工作的地点是：",
    },
    {
      id: "visa",
      complete: visaAnswered,
      label: visaAnswered ? `签证：${visa ? "需要担保" : "不需担保"}` : "签证：待补充",
      prompt: "关于签证担保，我的情况是：",
    },
  ];
}
