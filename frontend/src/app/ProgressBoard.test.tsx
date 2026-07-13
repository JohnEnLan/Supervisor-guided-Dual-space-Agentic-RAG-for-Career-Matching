import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProgressBoard } from "./ProgressBoard";

describe("ProgressBoard", () => {
  it("renders seven real stages without inventing a percentage", () => {
    render(
      <ProgressBoard
        completedStages={["resume", "intent"]}
        activeStage="retrieval"
        totalStages={7}
      />,
    );

    expect(screen.getByText("检索匹配", { selector: '[aria-current="step"]' })).toBeInTheDocument();
    expect(screen.getAllByText("第 3/7 阶段").length).toBeGreaterThan(0);
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.getAllByText("简历确认")[0].closest("li")).toHaveAttribute("data-state", "complete");
  });
});
