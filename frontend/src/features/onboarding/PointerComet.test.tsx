import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { POINTER_PARTICLE_COUNT, PointerComet } from "./PointerComet";

function stubPointerMedia({
  fine = true,
  reduced = false,
}: {
  fine?: boolean;
  reduced?: boolean;
}) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches:
        (query === "(pointer: fine)" && fine) ||
        (query === "(pointer: coarse)" && !fine) ||
        (query === "(prefers-reduced-motion: reduce)" && reduced),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("renders one fixed inert pool without replacing the system cursor", () => {
  stubPointerMedia({});
  const { container } = render(<PointerComet />);

  expect(screen.getByTestId("pointer-comet")).toHaveAttribute(
    "aria-hidden",
    "true",
  );
  expect(container.querySelectorAll(".pointer-comet-particle")).toHaveLength(
    POINTER_PARTICLE_COUNT,
  );
  expect(screen.getByTestId("pointer-comet")).toHaveStyle({
    pointerEvents: "none",
  });
});

it.each([
  { label: "coarse pointer", fine: false, reduced: false },
  { label: "reduced motion", fine: true, reduced: true },
])("does not attach tracking for $label", ({ fine, reduced }) => {
  stubPointerMedia({ fine, reduced });
  const add = vi.spyOn(window, "addEventListener");

  render(<PointerComet />);

  expect(add).not.toHaveBeenCalledWith(
    "pointermove",
    expect.any(Function),
    expect.anything(),
  );
});

it("reuses the same 18 nodes under pointer-move pressure and cleans up", () => {
  stubPointerMedia({});
  vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 17);
  const remove = vi.spyOn(window, "removeEventListener");
  const { container, unmount } = render(<PointerComet />);
  const originalNodes = Array.from(
    container.querySelectorAll(".pointer-comet-particle"),
  );

  for (let index = 0; index < 300; index += 1) {
    fireEvent.pointerMove(window, { clientX: index, clientY: index / 2 });
  }

  expect(
    Array.from(container.querySelectorAll(".pointer-comet-particle")),
  ).toEqual(originalNodes);
  unmount();
  expect(remove).toHaveBeenCalledWith("pointermove", expect.any(Function));
});
