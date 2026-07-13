import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { EvidenceDrawer } from "./EvidenceDrawer";

describe("EvidenceDrawer", () => {
  it("restores focus to its trigger after Escape", async () => {
    const user = userEvent.setup();
    render(<EvidenceDrawer title="Data Analyst" evidence={[{ evidence_span_id: "jd-1", content: "SQL is required" }]} resumeEvidence={[]} />);
    const trigger = screen.getByRole("button", { name: "查看证据" });
    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
  });
});
