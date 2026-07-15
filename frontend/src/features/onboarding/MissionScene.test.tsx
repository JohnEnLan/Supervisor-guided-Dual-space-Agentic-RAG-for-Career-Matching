import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EXPEDITION_CHAPTERS } from "./onboardingContent";
import { MissionScene } from "./MissionScene";

describe("cinematic expedition content", () => {
  it("defines seven ordered chapters covering the complete evidence mission", () => {
    expect(EXPEDITION_CHAPTERS).toHaveLength(7);
    expect(EXPEDITION_CHAPTERS.map((chapter) => chapter.id)).toEqual([
      "prologue",
      "fog",
      "coordinates",
      "direction",
      "fleet",
      "navigation",
      "departure",
    ]);

    const corpus = EXPEDITION_CHAPTERS.map(
      (chapter) => `${chapter.title} ${chapter.body} ${chapter.coordinate}`,
    ).join(" ");
    expect(corpus).toMatch(/目标岗位.*探索未知/);
    expect(corpus).toMatch(/Intent.*Matching.*Strategy.*Supervisor/);
    expect(corpus).toMatch(/显式岗位空间.*匿名案例空间/);
    expect(corpus).toMatch(/完整简历.*内部提示词.*API Key/);
  });

  it("renders one accessible mission scene with its coordinate", () => {
    render(<MissionScene chapter={EXPEDITION_CHAPTERS[2]} index={2} />);

    expect(
      screen.getByRole("heading", { name: "从已经发生的经历出发" }),
    ).toBeVisible();
    expect(
      screen.getByText("SKILL · PROJECT · EDUCATION · EXPERIENCE"),
    ).toBeVisible();
    expect(screen.getByRole("region")).toHaveAttribute(
      "id",
      "scene-coordinates",
    );
  });
});
