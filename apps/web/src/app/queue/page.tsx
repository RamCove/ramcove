import { AutoRefresh, TimeAgo } from "@/components/client";
import { Card, Empty, Notice, Pill, StatePill, Table, Td } from "@/components/ui";
import { apiGetOrNull } from "@/lib/api";
import { admissionKey, gain } from "@/lib/format";
import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Queue" };

type QueueItem = {
  submission_id: string;
  hotkey: string;
  lineage: string;
  state: string;
  state_label: string;
  admission_key: [number, number] | null;
  admitted_at: string | null;
  updated_at: string;
  current_stage: { stage: string; status: string; worker: string | null } | null;
  triage_gain_ppm: number | null;
  bound_gain_ppm: number | null;
  rebases_used: number;
  outcome: { code: string | null; summary: string | null; fee: string | null } | null;
};

type QueuePage = { kind: string; items: QueueItem[]; next_cursor: string | null; note: string };

const TABS = [
  { kind: "admitted", label: "Admitted (paid)" },
  { kind: "waiting", label: "Waiting list (free)" },
  { kind: "history", label: "Finished" },
];

export default async function QueuePage({
  searchParams,
}: {
  searchParams: Promise<{ kind?: string; cursor?: string }>;
}) {
  const sp = await searchParams;
  const kind = TABS.some((t) => t.kind === sp.kind) ? sp.kind! : "admitted";
  const qs = new URLSearchParams({ kind, ...(sp.cursor ? { cursor: sp.cursor } : {}) });
  const data = await apiGetOrNull<QueuePage>(`/v1/queue?${qs}`);
  return (
    <div className="min-w-0 space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">Queue and competition history</h1>
          <p className="mt-1 max-w-3xl text-[14px] leading-relaxed text-muted">
            Paid admissions are ordered by their finalized payment. The free waiting list is separate and costs
            nothing.
          </p>
        </div>
        <AutoRefresh seconds={6} />
      </header>

      <nav aria-label="Queue views" className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <Link
            key={t.kind}
            href={`/queue?kind=${t.kind}`}
            aria-current={t.kind === kind ? "page" : undefined}
            className={
              t.kind === kind
                ? "rounded-[var(--radius-sm)] border border-accent bg-accent-quiet px-3 py-1.5 text-[13px] text-accent-strong"
                : "rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-1.5 text-[13px] text-muted hover:text-text"
            }
          >
            {t.label}
          </Link>
        ))}
      </nav>

      <Notice tone="info" title="Order of work versus order of promotion">
        Workers may evaluate several submissions at the same time, so results finish out of order. Promotion
        still follows admission order: an earlier paid admission that is still active holds its place until it
        finishes or reaches a published deadline. A single rank across stages would be misleading, so none is
        shown.
      </Notice>

      <Card title={TABS.find((t) => t.kind === kind)!.label}>
        {!data ? (
          <Empty title="Queue unavailable">Start the API and reload.</Empty>
        ) : data.items.length === 0 ? (
          <Empty title="Nothing here yet">
            {kind === "admitted"
              ? "No paid submission is in progress."
              : kind === "waiting"
                ? "Nobody is waiting for capacity."
                : "No submission has finished yet."}
          </Empty>
        ) : (
          <>
            <Table
              caption="Submissions"
              head={
                kind === "admitted"
                  ? ["Submission", "Admission", "State", "Stage now", "Triage gain", "Updated"]
                  : kind === "waiting"
                    ? ["Submission", "Miner", "Lineage", "State", "Updated"]
                    : ["Submission", "Outcome", "Fee", "Confirmed gain", "Updated"]
              }
            >
              {data.items.map((it) => (
                <tr key={it.submission_id}>
                  <Td>
                    <Link href={`/submissions/${it.submission_id}`} className="text-accent hover:underline">
                      {it.submission_id.slice(0, 14)}…
                    </Link>
                    <div className="text-[11px] text-faint">{it.lineage}</div>
                  </Td>
                  {kind === "admitted" && (
                    <>
                      <Td className="num">{admissionKey(it.admission_key)}</Td>
                      <Td>
                        <StatePill state={it.state} label={it.state_label} />
                        {it.rebases_used > 0 && (
                          <div className="mt-1">
                            <Pill tone="warn">rebased {it.rebases_used}×</Pill>
                          </div>
                        )}
                      </Td>
                      <Td>
                        {it.current_stage ? (
                          <>
                            {it.current_stage.stage.replace(/_/g, " ")}
                            <div className="text-[11px] text-faint">
                              {it.current_stage.status}
                              {it.current_stage.worker ? ` · ${it.current_stage.worker}` : ""}
                            </div>
                          </>
                        ) : (
                          <span className="text-faint">—</span>
                        )}
                      </Td>
                      <Td className="num">{gain(it.triage_gain_ppm)}</Td>
                      <Td>{<TimeAgo at={it.updated_at} />}</Td>
                    </>
                  )}
                  {kind === "waiting" && (
                    <>
                      <Td>{it.hotkey}</Td>
                      <Td>{it.lineage}</Td>
                      <Td>
                        <StatePill state={it.state} label={it.state_label} />
                      </Td>
                      <Td>{<TimeAgo at={it.updated_at} />}</Td>
                    </>
                  )}
                  {kind === "history" && (
                    <>
                      <Td>
                        <StatePill state={it.state} label={it.state_label} />
                        {it.outcome?.summary && (
                          <div className="mt-1 max-w-md text-[11px] leading-snug text-muted">
                            {it.outcome.summary}
                          </div>
                        )}
                      </Td>
                      <Td>
                        {it.outcome?.fee ? (
                          <Pill tone={it.outcome.fee === "consumed" ? "neutral" : "warn"}>
                            {it.outcome.fee.replace(/_/g, " ")}
                          </Pill>
                        ) : (
                          "—"
                        )}
                      </Td>
                      <Td className="num">{gain(it.bound_gain_ppm)}</Td>
                      <Td>{<TimeAgo at={it.updated_at} />}</Td>
                    </>
                  )}
                </tr>
              ))}
            </Table>
            {data.next_cursor && (
              <div className="mt-3">
                <Link
                  href={`/queue?kind=${kind}&cursor=${encodeURIComponent(data.next_cursor)}`}
                  className="text-[13px] text-accent hover:underline"
                >
                  Next page →
                </Link>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
