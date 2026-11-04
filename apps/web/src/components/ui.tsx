import clsx from "clsx";
import type { ReactNode } from "react";

/** The top of every inner page: a mono eyebrow, a display headline and one plain sentence. */
export function PageHeader({
  eyebrow,
  title,
  lede,
  actions,
  children,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  lede?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="rise border-b border-line pb-8">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 max-w-3xl">
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h1 className="font-display text-balance mt-3 text-[36px] leading-[1.08] text-text sm:text-[46px]">
            {title}
          </h1>
          {lede && (
            <p className="mt-4 max-w-2xl text-[16px] leading-relaxed text-muted">
              {lede}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        )}
      </div>
      {children && <div className="mt-5">{children}</div>}
    </header>
  );
}

export function Card({
  title,
  subtitle,
  eyebrow,
  actions,
  children,
  className,
  id,
  flush,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
  /** Let the body reach the card edges, for tables and lists that draw their own rules. */
  flush?: boolean;
}) {
  return (
    <section
      id={id}
      className={clsx(
        "min-w-0 rounded-[var(--radius-card)] border border-line bg-surface",
        className,
      )}
      style={{ boxShadow: "var(--shadow)" }}
    >
      {(title || actions || eyebrow) && (
        <header className="flex flex-wrap items-start justify-between gap-3 px-6 pb-1 pt-5">
          <div className="min-w-0">
            {eyebrow && <p className="eyebrow mb-1.5">{eyebrow}</p>}
            {title && (
              <h2 className="text-[16px] font-semibold tracking-[-0.01em] text-text">
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="mt-1 max-w-2xl text-[14px] leading-relaxed text-muted">
                {subtitle}
              </p>
            )}
          </div>
          {actions && (
            <div className="flex shrink-0 items-center gap-2">{actions}</div>
          )}
        </header>
      )}
      <div className={flush ? "pb-2 pt-3" : "px-6 pb-6 pt-4"}>{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "accent" | "warn" | "danger" | "ok";
}) {
  const toneClass = {
    default: "text-text",
    accent: "text-accent-ink",
    warn: "text-warn",
    danger: "text-danger",
    ok: "text-ok",
  }[tone];
  return (
    <div className="min-w-0">
      <div className="eyebrow">{label}</div>
      <div
        className={clsx(
          "num mt-2 text-[26px] font-semibold leading-none tracking-[-0.02em]",
          toneClass,
        )}
      >
        {value}
      </div>
      {hint && (
        <div className="mt-2 text-[13px] leading-snug text-muted">{hint}</div>
      )}
    </div>
  );
}

const PILL_TONES: Record<string, string> = {
  neutral: "bg-surface-2 text-muted border-line",
  accent: "bg-accent-quiet text-accent-ink border-transparent",
  ok: "bg-ok-quiet text-ok border-transparent",
  warn: "bg-warn-quiet text-warn border-transparent",
  danger: "bg-danger-quiet text-danger border-transparent",
  info: "bg-info-quiet text-info border-transparent",
  sim: "bg-sim-quiet text-sim border-transparent",
};

export function Pill({
  tone = "neutral",
  children,
  title,
  dot,
}: {
  tone?: keyof typeof PILL_TONES;
  children: ReactNode;
  title?: string;
  dot?: boolean;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-[3px] text-[12px] font-medium leading-none",
        PILL_TONES[tone],
      )}
    >
      {dot && (
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
      )}
      {children}
    </span>
  );
}

/** State pill with an explicit text label; colour is never the only signal. */
export function StatePill({ state, label }: { state: string; label?: string }) {
  const tone =
    state === "promoted"
      ? "ok"
      : [
            "not_promoted",
            "rejected_screen",
            "rejected_preflight",
            "review_rejected",
            "expired_unregistered",
          ].includes(state)
        ? "danger"
        : ["operator_failed", "withdrawn"].includes(state)
          ? "warn"
          : ["in_review", "ready_for_promotion", "reproduce_queued"].includes(
                state,
              )
            ? "info"
            : ["waitlisted", "invited", "preflight_passed"].includes(
                  state,
                )
              ? "neutral"
              : "accent";
  return (
    <Pill tone={tone as keyof typeof PILL_TONES} dot>
      {label ?? state.replace(/_/g, " ")}
    </Pill>
  );
}

export function SimulatedTag({ what = "simulated" }: { what?: string }) {
  return (
    <Pill
      tone="sim"
      title="Produced in simulation mode by the simulated GPU workers"
    >
      {what}
    </Pill>
  );
}

/** Explains a term on first use: "Time until the first answer token (TTFT)". */
export function Term({
  term,
  plain,
  children,
}: {
  term: string;
  plain: string;
  children?: ReactNode;
}) {
  return (
    <abbr
      title={plain}
      className="cursor-help no-underline decoration-line-strong decoration-dotted underline-offset-4 [text-decoration-line:underline]"
    >
      {children ?? term}
    </abbr>
  );
}

export function Table({
  head,
  children,
  empty,
  caption,
  minWidth,
}: {
  head: ReactNode[];
  children: ReactNode;
  empty?: boolean;
  caption?: string;
  /** Below this width the table scrolls inside its card instead of squeezing columns. Defaults to
   *  roughly 130px per column, so narrow tables fit narrow cards. */
  minWidth?: number;
}) {
  const min = minWidth ?? Math.max(260, head.length * 130);
  return (
    <div className="table-scroll -mx-6 max-w-[calc(100%+3rem)] px-6">
      <table
        className="w-full border-collapse text-[14px]"
        style={{ minWidth: min }}
      >
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-line text-left">
            {head.map((h, i) => (
              <th
                key={i}
                scope="col"
                className="eyebrow whitespace-nowrap px-3 pb-3 pt-1 font-medium first:pl-0"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line [&>tr]:transition-colors [&>tr:hover]:bg-surface-2/60">
          {children}
        </tbody>
      </table>
      {empty && (
        <p className="px-0 py-8 text-[14px] text-muted">Nothing to show yet.</p>
      )}
    </div>
  );
}

export function Td({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <td className={clsx("px-3 py-3 align-top text-text first:pl-0", className)}>
      {children}
    </td>
  );
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-line-strong bg-surface/50 px-6 py-12 text-center">
      <p className="font-display text-[22px] text-text">{title}</p>
      {children && (
        <div className="mx-auto mt-2 max-w-md text-[14px] leading-relaxed text-muted">
          {children}
        </div>
      )}
    </div>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "danger" | "ok" | "sim";
  title: ReactNode;
  children?: ReactNode;
}) {
  const map = {
    info: ["bg-info-quiet", "bg-info"],
    warn: ["bg-warn-quiet", "bg-warn"],
    danger: ["bg-danger-quiet", "bg-danger"],
    ok: ["bg-ok-quiet", "bg-ok"],
    sim: ["bg-sim-quiet", "bg-sim"],
  } as const;
  const [bg, bar] = map[tone];
  return (
    <div
      className={clsx(
        "relative overflow-hidden rounded-[var(--radius-sm)] py-3.5 pl-5 pr-4",
        bg,
      )}
      role="note"
    >
      <span
        aria-hidden
        className={clsx("absolute inset-y-0 left-0 w-[3px]", bar)}
      />
      <p className="text-[14px] font-semibold text-text">{title}</p>
      {children && (
        <div className="mt-1 text-[14px] leading-relaxed text-muted">
          {children}
        </div>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={clsx("skeleton rounded-[var(--radius-sm)]", className)}
      aria-hidden
    />
  );
}

export function Mono({
  children,
  title,
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <span title={title} className="num font-mono text-[12.5px] text-muted">
      {children}
    </span>
  );
}

/** Label and value pairs. Two columns only when the card itself is wide enough, so the same component
 *  reads well in a main column and in a narrow sidebar. */
export function KeyValue({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <div className="@container">
      <dl className="grid grid-cols-1 gap-x-8 gap-y-4 @md:grid-cols-2">
        {rows.map(([k, v], i) => (
          <div key={i} className="min-w-0 border-t border-line pt-3">
            <dt className="eyebrow">{k}</dt>
            <dd className="num mt-1.5 break-words text-[14px] text-text">
              {v}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
