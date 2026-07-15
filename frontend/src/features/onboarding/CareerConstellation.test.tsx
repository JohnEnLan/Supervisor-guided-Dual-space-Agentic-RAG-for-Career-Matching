import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { CareerConstellation } from "./CareerConstellation";

it("activates only constellation signals reached by the current chapter", () => {
  const { rerender } = render(<CareerConstellation activeChapter={2} />);
  const figure = screen.getByRole("figure", { name: /职业证据星图/ });

  expect(figure).toHaveAttribute("data-chapter", "3");
  expect(figure.querySelectorAll("[data-activation].is-active")).toHaveLength(3);
  expect(screen.getByText("RESUME EVIDENCE")).toBeVisible();

  rerender(<CareerConstellation activeChapter={6} />);
  expect(figure.querySelectorAll("[data-activation].is-active")).toHaveLength(7);
  expect(screen.getByText("EVIDENCE OATH")).toBeVisible();
});
