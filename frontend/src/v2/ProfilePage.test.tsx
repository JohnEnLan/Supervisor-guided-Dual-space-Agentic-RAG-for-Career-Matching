import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { api } from "../api/queries";
import { ProfilePage } from "./ProfilePage";

function renderProfile() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ProfilePage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "me").mockResolvedValue({
    user_id: "user-1",
    status: "active",
    is_admin: false,
    display_name: "测试用户",
    created_at: "2026-08-06T10:00:00Z",
  });
});

describe("ProfilePage query state", () => {
  it("does not misrepresent a failed profile query as an empty profile and supports retry", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "meProfile")
      .mockRejectedValueOnce(new ApiError(500, "server_error"))
      .mockResolvedValueOnce({
        profile: { current_goal: ["backend engineer"] },
        updated_at: "2026-08-07T00:00:00Z",
      });
    renderProfile();

    expect(await screen.findByText("画像加载失败，请重试")).toBeVisible();
    expect(screen.queryByText(/还没有画像/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重试加载画像" }));
    await waitFor(() => expect(api.meProfile).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/backend engineer/)).toBeVisible();
  });
});
