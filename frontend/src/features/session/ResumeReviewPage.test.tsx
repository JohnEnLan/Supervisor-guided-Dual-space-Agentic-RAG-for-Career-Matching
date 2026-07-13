import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ResumePreview } from "../../api/queries";
import { ResumePreviewContent } from "./ResumeReviewPage";

const preview: ResumePreview = {
  session_id: "session-1",
  resume_version: 1,
  confirmed: false,
  skills: ["Python", "SQL"],
  experience: [{
    organization: "Example Lab",
    title: "Data Intern",
    location: "Birmingham",
    dates: "2025",
    achievements: ["Built a matching benchmark"],
    evidence_span_ids: ["span-1"],
  }],
  education: [{
    institution: "University of Birmingham",
    degree: "MSc",
    field: "Computer Science",
    dates: "2025–2026",
  }],
  projects: [],
  resume_quality_issues: ["部分项目缺少量化结果"],
  evidence: [{ evidence_span_id: "span-1", content: "Built a matching benchmark" }],
};

describe("ResumePreviewContent", () => {
  it("shows structured facts and exactly one primary confirmation action", () => {
    render(<ResumePreviewContent preview={preview} onConfirm={() => undefined} isConfirming={false} />);

    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("Data Intern")).toBeInTheDocument();
    expect(screen.getByText("部分项目缺少量化结果")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "确认简历" })).toHaveLength(1);
  });
});
