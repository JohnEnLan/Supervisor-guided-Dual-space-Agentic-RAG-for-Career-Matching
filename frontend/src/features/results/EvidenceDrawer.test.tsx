import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { EvidenceDrawer } from "./EvidenceDrawer";

describe("EvidenceDrawer", () => {
  it("renders a collapsed in-card accordion instead of a modal", () => {
    render(<EvidenceDrawer title="Data Analyst" evidence={[]} resumeEvidence={[]} />);

    const trigger = screen.getByRole("button", { name: "查看证据" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Agent 匹配理由" })).not.toBeInTheDocument();
  });

  it("expands all evidence sections inline and labels JD quotations", async () => {
    const user = userEvent.setup();
    render(
      <EvidenceDrawer
        title="Data Analyst"
        evidence={[{ evidence_span_id: "jd-1", content: "SQL is required" }]}
        resumeEvidence={[{ evidence_span_id: "resume-1", content: "Built SQL reports" }]}
      />,
    );

    const trigger = screen.getByRole("button", { name: "查看证据" });
    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("heading", { name: "Agent 匹配理由" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "岗位原文证据" })).toBeInTheDocument();
    expect(screen.getByText("出自 JD 原文")).toBeInTheDocument();
    expect(screen.getByText("SQL is required")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "简历事实证据" })).toBeInTheDocument();
    expect(screen.getByText("Built SQL reports")).toBeInTheDocument();
  });

  it("opens and closes from the keyboard while keeping focus on the trigger", async () => {
    const user = userEvent.setup();
    render(<EvidenceDrawer title="Data Analyst" evidence={[]} resumeEvidence={[]} />);
    const trigger = screen.getByRole("button", { name: "查看证据" });
    trigger.focus();
    await user.keyboard("{Enter}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveFocus();
    await user.keyboard(" ");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
});
