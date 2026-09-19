"use client";

import { usePreview } from "@/components/preview";
import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";

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
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-sm)] border font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 disabled:active:translate-y-0";
  const variants = {
    primary:
      "border-accent bg-accent text-on-accent shadow-[inset_0_1px_0_rgb(255_255_255/0.18),0_6px_18px_-8px_var(--accent)] hover:bg-accent-strong hover:border-accent-strong",
    secondary: "border-line-strong bg-surface text-text hover:border-text/40 hover:bg-surface-2",
    quiet: "border-transparent bg-transparent text-muted hover:bg-surface-2 hover:text-text",
    danger: "border-danger/50 bg-danger-quiet text-danger hover:border-danger hover:bg-danger hover:text-surface",
  }[variant];
  const sizes = { sm: "h-8 px-3 text-[13px]", md: "h-10 px-4 text-[14px]" }[size];
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

/** Polls a server route and refreshes the page data. Pauses when the tab is hidden. */
export function AutoRefresh({ seconds = 5 }: { seconds?: number }) {
  const router = useRouter();
  const { on: preview } = usePreview();
  const [on, setOn] = useState(true);
  useEffect(() => {
    if (!on || preview) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, seconds * 1000);
    return () => clearInterval(id);
  }, [on, preview, router, seconds]);
  if (preview) {
    // a snapshot never changes, so it must not look live
    return (
      <span className="inline-flex h-8 items-center gap-2 rounded-full border border-line bg-surface px-3 text-[12.5px] text-muted">
        <span aria-hidden className="inline-block h-[7px] w-[7px] rounded-full bg-sim" />
        Snapshot
      </span>
    );
  }
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => setOn((v) => !v)}
      className="inline-flex h-8 select-none items-center gap-2 rounded-full border border-line bg-surface px-3 text-[12.5px] text-muted transition-colors hover:text-text"
    >
      <span
        aria-hidden
        className={clsx(on ? "live-dot text-ok" : "inline-block h-[7px] w-[7px] rounded-full bg-faint")}
      />
      {on ? "Live" : "Paused"}
      <span className="sr-only"> updates</span>
      <span aria-hidden className="text-faint">·</span>
      <span className="text-faint">{on ? "pause" : "resume"}</span>
    </button>
  );
}

export function ThemeToggle() {
  // The inline script in the layout applies the stored theme before paint; read it from the DOM so the
  // server and the browser agree and no effect is needed.
  const theme = useSyncExternalStore(
    subscribeTheme,
    () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light"),
    () => "light" as const,
  );
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      aria-label={`Switch to the ${next} theme`}
      title={`Switch to the ${next} theme`}
      onClick={() => {
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem("ramcove-theme", next);
        } catch {
          /* private mode: the choice simply does not persist */
        }
        themeListeners.forEach((l) => l());
      }}
      className="inline-flex h-9 w-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-text"
    >
      {theme === "dark" ? (
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden>
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.5v2.2M12 19.3v2.2M4.3 4.3l1.6 1.6M18.1 18.1l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.3 19.7l1.6-1.6M18.1 5.9l1.6-1.6" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" aria-hidden>
          <path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7Z" />
        </svg>
      )}
    </button>
  );
}

const themeListeners = new Set<() => void>();

function subscribeTheme(listener: () => void) {
  themeListeners.add(listener);
  return () => themeListeners.delete(listener);
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

/** Relative time without a hydration mismatch: the server renders the absolute UTC time, the browser
 *  switches to "5 min ago" after mount. */
export function TimeAgo({ at }: { at: string | null | undefined }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    if (!at) return;
    const update = () => setText(agoText(at));
    update();
    const id = setInterval(update, 30_000);
    return () => clearInterval(id);
  }, [at]);
  if (!at) return <span className="text-faint">—</span>;
  const absolute = new Date(at).toISOString().replace("T", " ").slice(0, 16) + " UTC";
  return (
    <time dateTime={at} title={absolute} suppressHydrationWarning>
      {text ?? absolute}
    </time>
  );
}

function agoText(value: string): string {
  const secs = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (secs < 0) return "just now";
  if (secs < 45) return "just now";
  if (secs < 5400) return `${Math.round(secs / 60)} min ago`;
  if (secs < 172800) return `${Math.round(secs / 3600)} h ago`;
  return `${Math.round(secs / 86400)} days ago`;
}
