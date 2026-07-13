import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExplainUnavailable } from "./EvaluationRunPage";

describe("EvaluationRunPage", () => {
  it("explains when examiner capability is disabled", () => {
    render(<ExplainUnavailable />);
    expect(screen.getByText("评估解释未开启")).toBeInTheDocument();
    expect(screen.queryByText("内部提示词")).not.toBeInTheDocument();
  });
});
