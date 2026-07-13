import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReactionNotice } from "./ReactionForm";

describe("ReactionForm", () => {
  it("states that feedback is not automatically published", () => {
    render(<ReactionNotice />);
    expect(screen.getByText(/不会自动发布为匿名案例/)).toBeInTheDocument();
  });
});
