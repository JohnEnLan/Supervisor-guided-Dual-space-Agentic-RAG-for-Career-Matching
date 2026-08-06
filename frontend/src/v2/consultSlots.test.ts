import { describe, expect, it } from "vitest";

import { deriveConsultSlots } from "./consultSlots";

describe("consultation required-slot derivation", () => {
  it("matches the backend goal and location rules, including remote and invalid-list edges", () => {
    expect(
      deriveConsultSlots({
        current_goal: ["  ", "Platform engineer"],
        hard_constraints: { locations: ["  "] },
      }).map(({ id, complete, label }) => ({ id, complete, label })),
    ).toEqual([
      { id: "goal", complete: true, label: "目标：Platform engineer" },
      { id: "location", complete: false, label: "地点：待补充" },
      { id: "visa", complete: false, label: "签证：待补充" },
    ]);

    expect(
      deriveConsultSlots({
        current_goal: ["Platform engineer"],
        hard_constraints: { locations: ["London", ""] },
      })[1],
    ).toMatchObject({ complete: false, label: "地点：待补充" });
    expect(
      deriveConsultSlots({
        current_goal: ["Platform engineer"],
        hard_constraints: { locations: { city: "London" }, remote: true },
      })[1],
    ).toMatchObject({ complete: true, label: "地点：远程" });
  });

  it("treats both visa booleans as answered and never uses truthiness", () => {
    expect(
      deriveConsultSlots({ hard_constraints: { need_visa_sponsor: false } })[2],
    ).toMatchObject({ complete: true, label: "签证：不需担保" });
    expect(
      deriveConsultSlots({ hard_constraints: { need_visa_sponsor: true } })[2],
    ).toMatchObject({ complete: true, label: "签证：需要担保" });
    expect(
      deriveConsultSlots({ hard_constraints: { need_visa_sponsor: "false" } })[2],
    ).toMatchObject({ complete: false, label: "签证：待补充" });
  });

  it("adds resume clarification with answered, skipped, and remaining counts", () => {
    const slots = deriveConsultSlots(undefined, {
      answered: 1,
      skipped: 1,
      total: 3,
      questions_used: 2,
    });

    expect(slots).toHaveLength(4);
    expect(slots[3]).toEqual({
      id: "resume_clarification",
      complete: false,
      label: "简历补充：已回答 1，已跳过 1，待补充 1",
      prompt: "请继续帮我补充简历信息。",
    });
  });

  it("hides empty clarification targets and completes only when answered plus skipped equals total", () => {
    expect(
      deriveConsultSlots(undefined, { answered: 0, skipped: 0, total: 0, questions_used: 0 }),
    ).toHaveLength(3);
    expect(
      deriveConsultSlots(undefined, { answered: 1, skipped: 2, total: 3, questions_used: 2 })[3],
    ).toMatchObject({ complete: true, label: "简历补充：已回答 1，已跳过 2，待补充 0" });
    expect(
      deriveConsultSlots(undefined, { answered: 1, skipped: 1, total: 3, questions_used: 2 })[3],
    ).toMatchObject({ complete: false });
  });
});
