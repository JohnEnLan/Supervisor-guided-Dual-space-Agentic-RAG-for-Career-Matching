import { describe, expect, it } from "vitest";

import { runStatusRefetchInterval } from "./RunPage";

describe("runStatusRefetchInterval", () => {
  it("uses the server interval while running and stops in terminal states", () => {
    expect(runStatusRefetchInterval({ status: "running", retry_after_ms: 1700 })).toBe(1700);
    expect(runStatusRefetchInterval({ status: "completed", retry_after_ms: null })).toBe(false);
    expect(runStatusRefetchInterval({ status: "completed_with_warnings", retry_after_ms: null })).toBe(false);
    expect(runStatusRefetchInterval(undefined)).toBe(false);
  });
});
