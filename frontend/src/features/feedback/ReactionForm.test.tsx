import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/queries";
import { ReactionForm, ReactionNotice } from "./ReactionForm";

function renderReactionForm() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ReactionForm runId="run-1" jobId="job-1" />
    </QueryClientProvider>,
  );
}

describe("ReactionForm", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("states that feedback is not automatically published", () => {
    render(<ReactionNotice />);
    expect(screen.getByText(/不会自动发布为匿名案例/)).toBeInTheDocument();
  });

  it("offers only valid funnel outcomes without selecting one by default", async () => {
    const user = userEvent.setup();
    renderReactionForm();

    expect(screen.getByRole("heading", { name: "投递后回来告诉我们进展" })).toBeVisible();
    for (const [label, outcome] of [
      ["被拒", "rejected"],
      ["过筛", "passed_screen"],
      ["面试", "interview"],
      ["Offer", "offer"],
    ]) {
      expect(screen.getByRole("button", { name: label })).toHaveAttribute("value", outcome);
      expect(screen.getByRole("button", { name: label })).toHaveAttribute("aria-pressed", "false");
    }
    expect(screen.queryByText("有帮助")).not.toBeInTheDocument();
    expect(screen.queryByText("不相关")).not.toBeInTheDocument();
    expect(screen.queryByText("已投递")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交进展" })).toBeDisabled();

    expect(screen.queryByLabelText("备注（可选）")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "添加备注" }));
    expect(screen.getByLabelText("备注（可选）")).toBeVisible();
  });

  it.each([
    ["被拒", "rejected"],
    ["过筛", "passed_screen"],
    ["面试", "interview"],
    ["Offer", "offer"],
  ])("submits %s as the legal %s outcome", async (label, outcome) => {
    const user = userEvent.setup();
    vi.spyOn(api, "addReaction").mockResolvedValue({
      feedback_id: 1,
      run_id: "run-1",
      status: "reaction_recorded",
    });
    renderReactionForm();

    await user.click(screen.getByRole("button", { name: label }));
    await user.click(screen.getByRole("button", { name: "提交进展" }));

    await waitFor(() =>
      expect(api.addReaction).toHaveBeenCalledWith(
        "run-1",
        expect.objectContaining({ job_id: "job-1", outcome }),
      ),
    );
  });
});
