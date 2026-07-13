import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { EvidenceDrawer } from "./EvidenceDrawer";

describe("EvidenceDrawer", () => {
  it("keeps keyboard focus inside the open evidence dialog", async () => {
    const user = userEvent.setup();
    render(<EvidenceDrawer title="Data Analyst" evidence={[]} resumeEvidence={[]} />);
    await user.click(screen.getByRole("button", { name: "查看证据" }));
    expect(screen.getByRole("heading", { name: "Agent 匹配理由" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Must-have 命中" })).not.toBeInTheDocument();
    const close = screen.getByRole("button", { name: "关闭证据" });
    expect(close).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(close).toHaveFocus();
  });

  it("restores trigger focus after close button and backdrop close", async () => {
    const user = userEvent.setup();
    render(<EvidenceDrawer title="Data Analyst" evidence={[]} resumeEvidence={[]} />);
    const trigger = screen.getByRole("button", { name: "查看证据" });
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "关闭证据" }));
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    const backdrop = screen.getByRole("dialog").parentElement;
    expect(backdrop).not.toBeNull();
    await user.click(backdrop!);
    expect(trigger).toHaveFocus();
  });

  it("restores focus to its trigger after Escape", async () => {
    const user = userEvent.setup();
    render(<EvidenceDrawer title="Data Analyst" evidence={[{ evidence_span_id: "jd-1", content: "SQL is required" }]} resumeEvidence={[]} />);
    const trigger = screen.getByRole("button", { name: "查看证据" });
    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
  });
});
