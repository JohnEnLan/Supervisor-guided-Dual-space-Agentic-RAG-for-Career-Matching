import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AppProviders } from "../../app/providers";

import type { RunResult } from "../../api/queries";
import { ResultsContent } from "./ResultsPage";

const data: RunResult = {
  run_id: "run-1",
  status: "completed",
  result: {
    summary: "Two evidence-grounded recommendations",
    recommended_roles: [{ job_id: "job-1", title: "Data Analyst", company: "Example", location: "Birmingham", tier: "now_fit", listing_kind: "dataset_only", concise_explanation: "Matches SQL experience", why_this_match: ["SQL evidence"], evidence: [{ evidence_span_id: "jd-1", content: "Advanced SQL" }], resume_evidence: [] }],
    skill_gaps: [{ skill: "Power BI", gap: "Needs portfolio evidence", priority: "medium" }],
    resume_strategy: [], career_path: [], warnings: [],
  },
};

describe("ResultsContent", () => {
  it("renders one evidence-grounded list without a hiring probability", () => {
    render(<AppProviders><MemoryRouter><ResultsContent data={data} runId="run-1" /></MemoryRouter></AppProviders>);
    expect(screen.getByText("Data Analyst")).toBeInTheDocument();
    expect(screen.getByText("Advanced SQL")).toBeInTheDocument();
    expect(screen.queryByText(/录用概率|hiring probability|97%/i)).not.toBeInTheDocument();
  });

  it("shows the examiner entry only when the capability is enabled", () => {
    const { rerender } = render(<AppProviders><MemoryRouter><ResultsContent data={data} runId="run-1" explainEnabled={false} /></MemoryRouter></AppProviders>);
    expect(screen.queryByRole("link", { name: /查看评估解释/ })).not.toBeInTheDocument();
    rerender(<AppProviders><MemoryRouter><ResultsContent data={data} runId="run-1" explainEnabled /></MemoryRouter></AppProviders>);
    expect(screen.getByRole("link", { name: /查看评估解释/ })).toHaveAttribute("href", "/runs/run-1/evaluation");
  });
});
