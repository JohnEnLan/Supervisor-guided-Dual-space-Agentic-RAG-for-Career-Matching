import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { CinematicOnboardingPage } from "./CinematicOnboardingPage";

class ObserverStub {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();

  constructor(_callback: IntersectionObserverCallback) {}
}

afterEach(() => {
  vi.unstubAllGlobals();
});

it("renders seven scenes, chapter navigation, skip, and final departure", () => {
  vi.stubGlobal("IntersectionObserver", ObserverStub);
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      media: "",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );

  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<CinematicOnboardingPage />} />
        <Route path="/workspace" element={<h1>简历匹配工作台</h1>} />
      </Routes>
    </MemoryRouter>,
  );

  expect(
    screen.getByRole("heading", { level: 1, name: "职业远征" }),
  ).toBeVisible();
  expect(screen.getAllByRole("region")).toHaveLength(7);
  expect(
    screen.getByRole("navigation", { name: "远征章节" }),
  ).toBeVisible();
  expect(screen.getByRole("link", { name: /跳过远征/ })).toHaveAttribute(
    "href",
    "/workspace",
  );
  expect(
    screen.getByRole("link", { name: /进入职业匹配工作台/ }),
  ).toHaveAttribute("href", "/workspace");
  expect(
    screen.getByRole("heading", { name: /未来不由模型决定/ }),
  ).toBeVisible();
});
