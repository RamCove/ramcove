import { AutoRefresh, TimeAgo } from "@/components/client";
import { Card, Empty, Mono, Notice, PageHeader, Pill, StatePill, Table, Td } from "@/components/ui";
import { apiGetOrNull } from "@/lib/server-api";
import { admissionKey, gain, rps } from "@/lib/format";
import clsx from "clsx";
import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Dashboard" };

type Group = "in_progress" | "waiting" | "promoted" | "rejected" | "closed";

type Dashboard = {
  profile: { id: string; version: string; title: string };
  champion: {
    version: number;
    author: string | null;
    is_baseline: boolean;
    capacity_milli_rps: number | null;
    bound_gain_ppm: number | null;
    promoted_at: string | null;
  };
  counts: Record<Group, number>;
  total: number;
  items: {
    submission_id: string;
    hotkey: string | null;
    lineage: string;
    method: string | null;
    mechanism: string | null;
    trusted_fixture: string | null;
    state: string;
    state_label: string;
    group: Group;
    current_stage: { stage: string; status: string } | null;
    triage_gain_ppm: number | null;
    bound_gain_ppm: number | null;
    outcome: { code: string; summary: string; fee: string } | null;
    created_at: string;
    updated_at: string;
  }[];
  rejection_reasons: { code: string; count: number; example: string | null }[];
  miners: {
    hotkey: string | null;
    submissions: number;
    promoted: number;
    rejected: number;
    best_bound_gain_ppm: number | null;
    is_champion: boolean;
  }[];
};

type QueueItem = {
  submission_id: string;
  hotkey: string | null;
  lineage: string;
  state: string;
  state_label: string;
  admission_key: [number, number] | null;
  current_stage: { stage: string; status: string; worker: string | null } | null;
  updated_at: string;
};
type QueuePage = { items: QueueItem[] };

const GROUPS: { key: Group; label: string; hint: string; tone: string; bar: string }[] = [
  { key: "in_progress", label: "In evaluation", hint: "paid, being measured or reviewed", tone: "text-accent-ink", bar: "bg-accent" },
  { key: "waiting", label: "Waiting", hint: "checked, quoted or on the free list", tone: "text-text", bar: "bg-line-strong" },
  { key: "promoted", label: "Promoted", hint: "became the champion", tone: "text-ok", bar: "bg-ok" },
  { key: "rejected", label: "Rejected", hint: "did not clear the rules", tone: "text-danger", bar: "bg-danger" },
  { key: "closed", label: "Closed", hint: "withdrawn, expired or refunded", tone: "text-warn", bar: "bg-warn" },
];

const STAGE_NAMES: Record<string, string> = {
  screen: "screening",
  full: "full evaluation",
  confirm_block: "confirmation block",
  calibration: "calibration",
};

export default async function DashboardPage({ searchParams }: { searchParams: Promise<{ show?: string }> }) {
  const { show } = await searchParams;
  const [data, admitted, waiting] = await Promise.all([
    apiGetOrNull<Dashboard>("/v1/dashboard"),
    apiGetOrNull<QueuePage>("/v1/queue?kind=admitted"),
    apiGetOrNull<QueuePage>("/v1/queue?kind=waiting"),
  ]);
  if (!data) {
    return <Empty title="The dashboard is unavailable">Start the API and reload this page.</Empty>;
  }
  const filter = GROUPS.some((g) => g.key === show) ? (show as Group) : null;
  const items = filter ? data.items.filter((i) => i.group === filter) : data.items;
  const { champion } = data;

  return (
    <div className="min-w-0 space-y-8">
      <PageHeader
        eyebrow="For miners"
        title="Dashboard"
        lede="Where every submission stands: what is being measured, what is waiting, what won and why the others were rejected."
        actions={<AutoRefresh seconds={5} />}
      />

      <section className="grid gap-5 lg:grid-cols-[1.15fr_2fr]">
        <div
          className="flex flex-col justify-between rounded-[var(--radius-card)] border border-transparent bg-band p-6 text-on-band"
          style={{ boxShadow: "var(--shadow)" }}
        >
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-on-band/60">Current champion</p>
            <p className="font-display mt-3 text-[34px] leading-none">
              Version {champion.version}
              <span className="ml-2 text-[20px] italic text-on-band/60">
                {champion.is_baseline ? "baseline" : "challenger"}
              </span>
            </p>
            <p className="mt-3 text-[14px] text-on-band/70">
              {champion.is_baseline ? (
                "No miner holds the crown yet. The allocation is burned until one does."
              ) : (
                <>
                  Held by <span className="font-mono text-on-band">{champion.author}</span>
                </>
              )}
            </p>
          </div>
          <dl className="mt-8 grid grid-cols-2 gap-4 border-t border-on-band/15 pt-5">
            <div>
              <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-on-band/55">Capacity</dt>
              <dd className="num mt-1 font-mono text-[20px]">{rps(champion.capacity_milli_rps)}</dd>
            </div>
            <div>
              <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-on-band/55">Confirmed gain</dt>
              <dd className="num mt-1 font-mono text-[20px] text-accent">{gain(champion.bound_gain_ppm)}</dd>
            </div>
          </dl>
        </div>

        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-card)] border border-line bg-line sm:grid-cols-3 lg:grid-cols-5">
          {GROUPS.map((g) => {
            const active = filter === g.key;
            const n = data.counts[g.key] ?? 0;
            return (
              <Link
                key={g.key}
                href={active ? "/dashboard" : `/dashboard?show=${g.key}`}
                aria-current={active ? "true" : undefined}
                className={clsx(
                  "group relative flex flex-col bg-surface p-5 transition-colors hover:bg-bg",
                  active && "bg-bg",
                )}
              >
                <span className="eyebrow">{g.label}</span>
                <span className={clsx("num mt-3 font-mono text-[34px] leading-none tracking-[-0.03em]", g.tone)}>
                  {n}
                </span>
                <span className="mt-2 flex-1 text-[12.5px] leading-snug text-muted">{g.hint}</span>
                <span className="mt-4 h-1 rounded-full bg-surface-3">
                  <span
                    className={clsx("block h-full rounded-full", g.bar)}
                    style={{ width: `${data.total ? Math.max(4, Math.round((n / data.total) * 100)) : 0}%` }}
                  />
                </span>
                {active && <span aria-hidden className="absolute inset-x-0 top-0 h-[2px] bg-accent" />}
              </Link>
            );
          })}
        </div>
      </section>

      <section id="queue" className="scroll-mt-24 space-y-5">
        <div className="grid items-start gap-5 lg:grid-cols-[1.6fr_1fr]">
          <Card
            eyebrow="Order of work"
            title="Paid, in the order they are tested"
            subtitle="Ordered by when each payment was finalized on the chain. Finishing first never lets a later submission jump ahead."
          >
            {!admitted || admitted.items.length === 0 ? (
              <p className="py-3 text-[14px] text-muted">No paid submission is being evaluated right now.</p>
            ) : (
              <ol className="divide-y divide-line">
                {admitted.items.map((it, i) => (
                  <li key={it.submission_id} className="flex items-start gap-4 py-3.5">
                    <span className="num w-8 shrink-0 pt-0.5 font-mono text-[20px] leading-none text-accent-ink">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <Link
                        href={`/submissions/${it.submission_id}`}
                        className="font-medium text-text hover:underline"
                      >
                        {it.lineage}
                      </Link>
                      <p className="num mt-0.5 font-mono text-[11.5px] text-faint">
                        {it.hotkey ?? "—"} · paid at {admissionKey(it.admission_key)}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <StatePill state={it.state} label={it.state_label} />
                      {it.current_stage && (
                        <p className="mt-1 text-[12px] text-muted">
                          {STAGE_NAMES[it.current_stage.stage] ?? it.current_stage.stage} · {it.current_stage.status}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>
          <Card
            eyebrow="Waiting list"
            title="Free, waiting for capacity"
            subtitle="No fee is taken. When capacity frees up, the oldest waiting submission is invited to pay."
          >
            {!waiting || waiting.items.length === 0 ? (
              <p className="py-3 text-[14px] text-muted">Nobody is waiting.</p>
            ) : (
              <ol className="divide-y divide-line">
                {waiting.items.map((it, i) => (
                  <li key={it.submission_id} className="flex items-center gap-3 py-3">
                    <span className="num w-6 shrink-0 font-mono text-[14px] text-faint">{i + 1}</span>
                    <Link
                      href={`/submissions/${it.submission_id}`}
                      className="min-w-0 flex-1 truncate text-[14px] text-text hover:underline"
                    >
                      {it.lineage}
                    </Link>
                    <StatePill state={it.state} label={it.state_label} />
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>
        <Notice tone="info" title="Order of work versus order of promotion">
          Workers can test several submissions at once, so results can finish out of order. A crown still
          changes hands in payment order: an earlier paid submission that is still being tested keeps its place
          until it finishes or reaches its published deadline.
        </Notice>
      </section>

      <Card
        eyebrow={filter ? `Showing: ${GROUPS.find((g) => g.key === filter)?.label}` : "All submissions"}
        title={`${items.length} submission${items.length === 1 ? "" : "s"}`}
        subtitle="Newest activity first. Open a row for its full timeline, measurements and reviews."
        actions={
          filter ? (
            <Link href="/dashboard" className="link text-[14px]">
              Show all
            </Link>
          ) : undefined
        }
      >
        {items.length === 0 ? (
          <Empty title={filter ? "Nothing in this group" : "No submissions yet"}>
            {filter ? "Choose another group above." : "The first submission will appear here as soon as it passes the free checks."}
          </Empty>
        ) : (
          <Table head={["Submission", "Miner", "Status", "Gain", "Outcome", "Updated"]} minWidth={900}>
            {items.map((s) => (
              <tr key={s.submission_id}>
                <Td>
                  <Link href={`/submissions/${s.submission_id}`} className="group block">
                    <span className="block font-medium text-text group-hover:underline">
                      {s.method ?? s.trusted_fixture ?? s.lineage}
                    </span>
                    <span className="num mt-0.5 block font-mono text-[11.5px] text-faint">{s.submission_id}</span>
                  </Link>
                </Td>
                <Td className="whitespace-nowrap">
                  <Mono>{s.hotkey ?? "—"}</Mono>
                </Td>
                <Td>
                  <StatePill state={s.state} label={s.state_label} />
                  {s.current_stage && (
                    <span className="mt-1.5 block text-[12px] text-muted">
                      {STAGE_NAMES[s.current_stage.stage] ?? s.current_stage.stage} · {s.current_stage.status}
                    </span>
                  )}
                </Td>
                <Td className="num whitespace-nowrap font-mono text-[13px]">
                  {s.bound_gain_ppm !== null ? (
                    <span title="Confirmed lower bound">{gain(s.bound_gain_ppm)}</span>
                  ) : s.triage_gain_ppm !== null ? (
                    <span className="text-muted" title="Triage estimate, not promotion evidence">
                      ~{gain(s.triage_gain_ppm)}
                    </span>
                  ) : (
                    <span className="text-faint">—</span>
                  )}
                </Td>
                <Td className="max-w-[320px] text-[13px] leading-snug text-muted">
                  {s.outcome?.summary ? (
                    <span className="line-clamp-3" title={s.outcome.summary}>
                      {s.outcome.summary}
                    </span>
                  ) : (
                    <span className="text-faint">in progress</span>
                  )}
                </Td>
                <Td className="whitespace-nowrap text-[13px] text-muted">
                  <TimeAgo at={s.updated_at} />
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Card
          eyebrow="Rejected"
          title="Why submissions were rejected"
          subtitle="Every rejection names the rule it failed. The fee is consumed once measurement has run."
        >
          {data.rejection_reasons.length === 0 ? (
            <p className="py-4 text-[14px] text-muted">No rejections yet.</p>
          ) : (
            <ul className="divide-y divide-line">
              {data.rejection_reasons.map((r) => (
                <li key={r.code} className="flex gap-4 py-3.5">
                  <span className="num w-10 shrink-0 font-mono text-[22px] leading-none text-danger">{r.count}</span>
                  <div className="min-w-0">
                    <Pill tone="danger">{r.code.replace(/_/g, " ")}</Pill>
                    {r.example && (
                      <p className="mt-1.5 line-clamp-3 text-[13px] leading-snug text-muted" title={r.example}>
                        {r.example}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card eyebrow="Miners" title="Who is competing" subtitle="Masked hotkeys, with each miner's record so far.">
          {data.miners.length === 0 ? (
            <p className="py-4 text-[14px] text-muted">No miners yet.</p>
          ) : (
            <Table head={["Miner", "Sent", "Won", "Rejected", "Best gain"]} minWidth={400}>
              {data.miners.map((m) => (
                <tr key={m.hotkey ?? "unknown"}>
                  <Td className="whitespace-nowrap">
                    <span className="inline-flex items-center gap-2">
                      <Mono>{m.hotkey ?? "—"}</Mono>
                      {m.is_champion && (
                        <Pill tone="ok" dot>
                          champion
                        </Pill>
                      )}
                    </span>
                  </Td>
                  <Td className="num font-mono text-[13px]">{m.submissions}</Td>
                  <Td className="num font-mono text-[13px] text-ok">{m.promoted}</Td>
                  <Td className="num font-mono text-[13px] text-danger">{m.rejected}</Td>
                  <Td className="num font-mono text-[13px]">{gain(m.best_bound_gain_ppm)}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </div>
  );
}
