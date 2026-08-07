import { useEffect, useRef, type ReactNode } from "react";

/** Shared accessible modal used by workbench recovery flows and shell-level quota errors. */
export function FocusModal({
  label,
  onClose,
  closeDisabled = false,
  modeKey,
  children,
}: {
  label: string;
  onClose: () => void;
  closeDisabled?: boolean;
  modeKey?: string;
  children: ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      const target = restoreTo.current;
      queueMicrotask(() => target?.focus());
    };
  }, []);

  useEffect(() => {
    container.current?.focus();
  }, [modeKey]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!closeDisabled) onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        container.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (!focusable.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === container.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || active === container.current)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeDisabled, onClose]);

  return (
    <div className="v2-modal-backdrop" role="dialog" aria-modal="true" aria-label={label}>
      <div className="v2-modal" ref={container} tabIndex={-1}>
        {children}
      </div>
    </div>
  );
}
