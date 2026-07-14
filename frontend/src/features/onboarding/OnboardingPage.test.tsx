import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { OnboardingPage } from "./OnboardingPage";

function renderOnboarding() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<OnboardingPage />} />
        <Route path="/workspace" element={<h1>简历匹配工作台</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("OnboardingPage", () => {
  it("moves through all three screens and enters the workspace", () => {
    renderOnboarding();

    expect(
      screen.getByRole("heading", { name: /有证据的职业决策/ }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: /有证据的职业决策/ }),
    ).not.toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "了解它如何工作" }));
    expect(screen.getByRole("heading", { name: /Agent 协作/ })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "继续了解" }));
    expect(
      screen.getByRole("heading", { name: /可信、可解释/ }),
    ).toHaveFocus();

    fireEvent.click(
      screen.getByRole("link", { name: "进入职业匹配工作台" }),
    );
    expect(
      screen.getByRole("heading", { name: "简历匹配工作台" }),
    ).toBeVisible();
  });

  it("returns to the previous screen and skips from every screen", () => {
    renderOnboarding();

    expect(screen.getByRole("link", { name: "跳过介绍" })).toHaveAttribute(
      "href",
      "/workspace",
    );

    fireEvent.click(screen.getByRole("button", { name: "了解它如何工作" }));
    fireEvent.click(screen.getByRole("button", { name: "上一页" }));
    expect(
      screen.getByRole("heading", { name: /有证据的职业决策/ }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("link", { name: "跳过介绍" }));
    expect(
      screen.getByRole("heading", { name: "简历匹配工作台" }),
    ).toBeVisible();
  });
});
