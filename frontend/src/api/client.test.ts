import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  it("returns the typed JSON body for a successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ session_id: "session-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const result = await apiRequest<{ session_id: string }>("/sessions");

    expect(result.session_id).toBe("session-1");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/sessions",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("projects a recoverable FastAPI conflict into ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              message: "The match brief is stale.",
              error_code: "STALE_PLAN",
              recovery: {
                action: "poll_status",
                status_url: "/api/v1/runs/run-1/status",
              },
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const promise = apiRequest("/runs/run-1/result");

    await expect(promise).rejects.toEqual(
      expect.objectContaining<ApiError>({
        name: "ApiError",
        status: 409,
        message: "The match brief is stale.",
        errorCode: "STALE_PLAN",
        recovery: {
          action: "poll_status",
          status_url: "/api/v1/runs/run-1/status",
        },
      }),
    );
  });

  it("uses a safe fallback when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("gateway unavailable", { status: 502 })),
    );

    await expect(apiRequest("/capabilities")).rejects.toMatchObject({
      status: 502,
      message: "Request failed with status 502.",
    });
  });
});
