import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api } from "../api/queries";
import { LandingPage } from "./LandingPage";

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "me").mockRejectedValue(new ApiError(401, "unauthorized"));
  vi.spyOn(api, "capabilities").mockResolvedValue({
    api_version: "v1",
    dual_space_enabled: true,
    resume_image_upload_enabled: true,
    execution_durability: "process_local",
    explain_enabled: false,
    monitoring_enabled: false,
    otp_channels: ["email"],
  });
});

describe("LandingPage product claims", () => {
  it("describes database filtering within its implemented field scope", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter([{ path: "/", element: <LandingPage /> }]);
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(
        "已支持的硬条件（地点、签证担保要求、学历、经验等）由数据库过滤；其余偏好参与检索排序",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/AI 无权放宽/)).not.toBeInTheDocument();
  });
});
