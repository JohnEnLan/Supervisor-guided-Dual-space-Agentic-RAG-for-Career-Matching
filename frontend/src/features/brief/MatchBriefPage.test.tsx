import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IntentModeFields, buildBriefRequest } from "./MatchBriefPage";

describe("MatchBriefPage consultation", () => {
  it("shows target role and company fields only for targeted mode", () => {
    const { rerender } = render(<IntentModeFields mode="targeted" />);
    expect(screen.getByLabelText("目标岗位")).toBeInTheDocument();
    expect(screen.getByLabelText("目标公司")).toBeInTheDocument();

    rerender(<IntentModeFields mode="explore" />);
    expect(screen.queryByLabelText("目标岗位")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("目标公司")).not.toBeInTheDocument();
  });

  it("keeps exclusive companies in hard constraints", () => {
    const brief = buildBriefRequest({
      careerGoal: "Become a data analyst in the UK market",
      locations: "Birmingham, London",
      visa: "Skilled Worker sponsorship",
      roleFamilies: "Data Analyst, BI Analyst",
      avoidRoles: "Sales",
      companies: "Example Ltd",
      companyExclusive: true,
      resultCount: 5,
    });

    expect(brief.hard_constraints?.companies).toEqual(["Example Ltd"]);
    expect(brief.soft_preferences?.preferred_companies).toBeUndefined();
    expect(brief.avoid_roles).toEqual(["Sales"]);
  });
});
