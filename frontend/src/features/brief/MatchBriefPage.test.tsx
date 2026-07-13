import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { IntentConsult } from "../../api/queries";
import { IntentModeFields, buildBriefRequest, consultationToForm } from "./MatchBriefPage";

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
    expect(brief.hard_constraints?.need_visa_sponsor).toBe(true);
    expect(brief.soft_preferences?.preferred_role_clusters).toEqual(["Data Analyst", "BI Analyst"]);
    expect(brief.soft_preferences?.preferred_companies).toBeUndefined();
    expect(brief.avoid_roles).toEqual(["Sales"]);
  });

  it("restores every approved brief field from durable consultation", () => {
    const consultation: IntentConsult = {
      session_id: "session-1",
      mode: "targeted",
      assistant_message: "Approved",
      current_goal: ["Become a data analyst in the UK"],
      hard_constraints: {
        locations: ["Birmingham"],
        need_visa_sponsor: true,
        companies: ["Example Ltd"],
      },
      soft_preferences: { preferred_role_clusters: ["Data Analyst", "BI Analyst"] },
      avoid_roles: ["Sales"],
      directions: [],
      needs_clarification: false,
      clarification_used: 0,
    };

    expect(consultationToForm(consultation)).toMatchObject({
      careerGoal: "Become a data analyst in the UK",
      locations: "Birmingham",
      visa: "需要签证担保",
      roleFamilies: "Data Analyst, BI Analyst",
      avoidRoles: "Sales",
      companies: "Example Ltd",
      companyExclusive: true,
    });
  });
});
