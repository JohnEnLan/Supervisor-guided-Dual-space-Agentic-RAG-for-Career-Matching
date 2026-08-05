import { describe, expect, it } from "vitest";

import { PERSONAS, conversationInterval, statusInterval } from "./WorkbenchPage";

describe("v2 polling intervals", () => {
  it("follows server pacing while running and stops on terminal states", () => {
    expect(conversationInterval({ status: "running", next_poll_ms: 1500 })).toBe(1500);
    expect(conversationInterval({ status: "completed", next_poll_ms: null })).toBe(false);
    expect(conversationInterval(undefined)).toBe(false);
    expect(statusInterval({ status: "running", retry_after_ms: 900 })).toBe(900);
    expect(statusInterval({ status: "failed", retry_after_ms: 900 })).toBe(false);
  });
});

describe("v2 personas", () => {
  it("covers the four service personas plus the user", () => {
    expect(Object.keys(PERSONAS).sort()).toEqual([
      "intent_consultant",
      "job_scout",
      "pm",
      "strategist",
      "user",
    ]);
  });
});
