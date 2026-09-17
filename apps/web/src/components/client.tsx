"use client";

import { ApiFailure, clientFetch } from "@/lib/api";
import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";

export type Session = { hotkey: string; demo: boolean; roles: string[] } | null;

export function Button({
  children,
  onClick,
  variant = "secondary",
  type = "button",
  disabled,
  busy,
  size = "md",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "quiet" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  busy?: boolean;
  size?: "sm" | "md";
  title?: string;
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-[var(--radius-sm)] border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55";
  const variants = {
    primary: "border-accent bg-accent text-[#04201e] hover:bg-accent-strong",
    secondary: "border-line-strong bg-surface-2 text-text hover:bg-surface-3",
    quiet: "border-transparent bg-transparent text-muted hover:text-text hover:bg-surface-2",
    danger: "border-danger bg-danger-quiet text-danger hover:bg-danger hover:text-[#1b0e0c]",
  }[variant];
  const sizes = { sm: "px-2.5 py-1 text-[12px]", md: "px-3.5 py-2 text-[13px]" }[size];
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={clsx(base, variants, sizes)}
    >
      {busy && (
        <span
          aria-hidden
          className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  );
}

/** Confirmation for consequential actions. Uses the native dialog element for focus and Escape handling. */
export function ConfirmButton({
  label,
  title,
  body,
  confirmLabel,
  onConfirm,
  variant = "secondary",
  disabled,
  size,
}: {
  label: ReactNode;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<void> | void;
  variant?: "primary" | "secondary" | "quiet" | "danger";
  disabled?: boolean;
  size?: "sm" | "md";
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const id = useId();
  return (
    <>
      <Button variant={variant} disabled={disabled} size={size} onClick={() => ref.current?.showModal()}>
        {label}
      </Button>
      <dialog
        ref={ref}
        aria-labelledby={`${id}-title`}
        className="w-[min(30rem,92vw)] rounded-[var(--radius-card)] border border-line bg-surface p-0 text-text backdrop:bg-black/60"
      >
        <div className="px-5 py-4">
          <h2 id={`${id}-title`} className="text-[15px] font-semibold">
            {title}
          </h2>
          <div className="mt-2 text-[13px] leading-relaxed text-muted">{body}</div>
        </div>
        <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <Button variant="quiet" onClick={() => ref.current?.close()}>
            Cancel
          </Button>
          <Button
            variant={variant === "danger" ? "danger" : "primary"}
            busy={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                ref.current?.close();
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      </dialog>
    </>
  );
}

export function useSession() {
  const [session, setSession] = useState<Session>(null);
  const [loaded, setLoaded] = useState(false);
  const reload = useCallback(async () => {
    try {
      const r = await clientFetch<{ session: Session }>("/v1/auth/me");
      setSession(r.session);
    } catch {
      setSession(null);
    } finally {
      setLoaded(true);
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { session, loaded, reload };
}

export function ErrorText({ error }: { error: ApiFailure | Error | null }) {
  if (!error) return null;
  const ref = error instanceof ApiFailure ? error.error.reference : undefined;
  return (
    <p role="alert" className="mt-2 text-[13px] text-danger">
      {error.message}
      {ref && (
        <>
          {" "}
          <span className="num font-mono text-[12px] text-muted">reference {ref}</span>
        </>
      )}
    </p>
  );
}

/** Polls a server route and refreshes the page data. Pauses when the tab is hidden. */
export function AutoRefresh({ seconds = 5 }: { seconds?: number }) {
  const router = useRouter();
  const [on, setOn] = useState(true);
  useEffect(() => {
    if (!on) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, seconds * 1000);
    return () => clearInterval(id);
  }, [on, router, seconds]);
  return (
    <label className="inline-flex cursor-pointer select-none items-center gap-2 text-[12px] text-muted">
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => setOn(e.target.checked)}
        className="h-3.5 w-3.5 accent-[var(--accent)]"
      />
      Live updates
    </label>
  );
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  useEffect(() => {
    const stored = (localStorage.getItem("room-theme") as "dark" | "light" | null) ?? "dark";
    setTheme(stored);
    document.documentElement.dataset.theme = stored;
  }, []);
  return (
    <Button
      variant="quiet"
      size="sm"
      title="Switch between the dark and light theme"
      onClick={() => {
        const next = theme === "dark" ? "light" : "dark";
        setTheme(next);
        document.documentElement.dataset.theme = next;
        localStorage.setItem("room-theme", next);
      }}
    >
      {theme === "dark" ? "Light theme" : "Dark theme"}
    </Button>
  );
}

export function CopyRef({ value, label = "Copy" }: { value: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      variant="quiet"
      size="sm"
      title={`Copy ${value}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          setDone(false);
        }
      }}
    >
      {done ? "Copied" : label}
    </Button>
  );
}
