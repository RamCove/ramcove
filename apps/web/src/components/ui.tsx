import clsx from "clsx";
import type { ReactNode } from "react";

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  id,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section
      id={id}
      className={clsx("rounded-[var(--radius-card)] border border-line bg-surface", className)}
      style={{ boxShadow: "var(--shadow)" }}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold tracking-tight text-text">{title}</h2>}
            {subtitle && <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
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
    accent: "text-accent-strong",
    warn: "text-warn",
    danger: "text-danger",
    ok: "text-ok",
  }[tone];
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-faint">{label}</div>
      <div className={clsx("num mt-1 text-[22px] font-semibold leading-tight", toneClass)}>{value}</div>
      {hint && <div className="mt-1 text-[12px] leading-snug text-muted">{hint}</div>}
    </div>
  );
}

const PILL_TONES: Record<string, string> = {
  neutral: "bg-surface-3 text-muted border-line-strong",
  accent: "bg-accent-quiet text-accent-strong border-accent",
  ok: "bg-ok-quiet text-ok border-ok",
  warn: "bg-warn-quiet text-warn border-warn",
  danger: "bg-danger-quiet text-danger border-danger",
  info: "bg-info-quiet text-info border-info",
  sim: "bg-sim-quiet text-sim border-sim",
};

export function Pill({
  tone = "neutral",
  children,
  title,
}: {
  tone?: keyof typeof PILL_TONES;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-[2px] text-[11px] font-medium",
        PILL_TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

/** State pill with an explicit text label; colour is never the only signal. */
export function StatePill({ state, label }: { state: string; label?: string }) {
  const tone =
    state === "promoted"
      ? "ok"
      : ["not_promoted", "rejected_screen", "rejected_preflight", "review_rejected", "expired_unregistered"].includes(
            state,
          )
        ? "danger"
        : ["operator_failed", "expired_quote", "withdrawn"].includes(state)
          ? "warn"
          : ["in_review", "ready_for_promotion"].includes(state)
            ? "info"
            : ["waitlisted", "invited", "quoted", "preflight_passed"].includes(state)
              ? "neutral"
              : "accent";
  return <Pill tone={tone as keyof typeof PILL_TONES}>{label ?? state.replace(/_/g, " ")}</Pill>;
}

export function SimulatedTag({ what = "simulated" }: { what?: string }) {
  return (
    <Pill tone="sim" title="Produced by a labelled simulation in this local build, not measured on real hardware">
      {what}
    </Pill>
  );
}

/** Explains a term on first use: "Time until the first answer token (TTFT)". */
export function Term({ term, plain, children }: { term: string; plain: string; children?: ReactNode }) {
  return (
    <abbr
      title={plain}
      className="cursor-help border-b border-dotted border-line-strong no-underline decoration-dotted"
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
}: {
  head: ReactNode[];
  children: ReactNode;
  empty?: boolean;
  caption?: string;
}) {
  return (
    <div className="table-scroll -mx-5 px-5">
      <table className="w-full min-w-[640px] border-collapse text-[13px]">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-line text-left">
            {head.map((h, i) => (
              <th
                key={i}
                scope="col"
                className="whitespace-nowrap px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-faint first:pl-0"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
      {empty && <p className="px-3 py-6 text-[13px] text-muted">Nothing to show yet.</p>}
    </div>
  );
}

export function Td({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={clsx("px-3 py-2 align-top text-text first:pl-0", className)}>{children}</td>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-line px-5 py-8 text-center">
      <p className="text-[14px] font-medium text-text">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-md text-[13px] leading-relaxed text-muted">{children}</div>}
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
    info: "border-info bg-info-quiet",
    warn: "border-warn bg-warn-quiet",
    danger: "border-danger bg-danger-quiet",
    ok: "border-ok bg-ok-quiet",
    sim: "border-sim bg-sim-quiet",
  } as const;
  return (
    <div className={clsx("rounded-[var(--radius-sm)] border-l-2 px-4 py-3", map[tone])} role="note">
      <p className="text-[13px] font-semibold text-text">{title}</p>
      {children && <div className="mt-1 text-[13px] leading-relaxed text-muted">{children}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("skeleton rounded-[var(--radius-sm)]", className)} aria-hidden />;
}

export function Mono({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span title={title} className="num font-mono text-[12px] text-muted">
      {children}
    </span>
  );
}

export function KeyValue({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
      {rows.map(([k, v], i) => (
        <div key={i} className="min-w-0">
          <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-faint">{k}</dt>
          <dd className="num mt-[2px] break-words text-[13px] text-text">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
