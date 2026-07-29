import { describe, expect, it } from "vitest";

import { conversationRefetchInterval, PERSONA_META } from "./ChatPage";

describe("conversationRefetchInterval", () => {
  it("uses the server interval while running and stops in terminal states", () => {
    expect(conversationRefetchInterval({ status: "running", next_poll_ms: 1500 })).toBe(1500);
    expect(conversationRefetchInterval({ status: "completed", next_poll_ms: null })).toBe(false);
    expect(
      conversationRefetchInterval({ status: "completed_with_warnings", next_poll_ms: null }),
    ).toBe(false);
    expect(conversationRefetchInterval({ status: "failed", next_poll_ms: 1500 })).toBe(false);
    expect(conversationRefetchInterval(undefined)).toBe(false);
  });
});

describe("PERSONA_META", () => {
  it("covers all four backend personas", () => {
    expect(Object.keys(PERSONA_META).sort()).toEqual([
      "intent_consultant",
      "job_scout",
      "pm",
      "strategist",
    ]);
  });
});
