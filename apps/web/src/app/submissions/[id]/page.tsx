import { AutoRefresh, CopyRef, TimeAgo } from "@/components/client";
import {
  Card,
  Empty,
  KeyValue,
  Mono,
  Notice,
  PageHeader,
  Pill,
  SimulatedTag,
  Stat,
  StatePill,
  Table,
  Td,
  Term,
} from "@/components/ui";
import { apiGetOrNull } from "@/lib/server-api";
import {
  admissionKey,
  centiHours,
  gain,
  rps,
  shortHash,
  when,
} from "@/lib/format";
import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Submission" };

type View = {
  submission_id: string;
  state: string;
  state_label: string;
  hotkey: string;
  lineage: string;
  profile_id: string;
  profile_version: string;
  rule_hash: string;
  support_ref: string;
  created_at: string;
  updated_at: string;
  admission_key: [number, number] | null;
  admitted_at: string | null;
  compared_champion_version: number | null;
  current_champion_version: number;
  first_gain_ppm: number | null;
  bound_gain_ppm: number | null;
  margin_ppm: number;
  clear_win_ppm: number;
  outcome: { code: string | null; summary: string | null };
  method: string | null;
  mechanism: string | null;
  trusted_fixture: string | null;
  blocking_submissions: string[];
  registration_deadline: string | null;
  timeline: {
    stage: string;
    status: string;
    worker: string | null;
    champion_version: number | null;
    attempts: number;
    created_at: string;
    updated_at: string;
    lease_expires_at: string | null;
    gpu_centi_used: number | null;
  }[];
  comparisons: {
    id: string;
    champion_version: number;
    status: string;
    validator: string;
    worker: string;
    anchor_block: number;
    beacon_round: number;
    beacon_simulated: boolean;
    void_reason: string | null;
    challenger_milli_rps: number | null;
    champion_milli_rps: number | null;
  }[];
  reviews: {
    id: string;
    reviewer: string;
    decision: string | null;
    criteria: {
      id: string;
      title: string;
      passed?: boolean;
      flagged?: boolean;
    }[];
    reasons: string | null;
    due_at: string;
    decided_at: string | null;
  }[];
  appeals: {
    id: string;
    status: string;
    kind: string;
    grounds: string;
    decision_reason: string | null;
    due_at: string;
  }[];
  reports: {
    id: string;
    kind: string;
    hash: string;
    simulated: boolean;
    body: Record<string, unknown> | null;
    created_at: string;
  }[];
};

const STAGE_TITLE: Record<string, string> = {
  screen: "Screening",
  full: "Evaluation",
  reproduce: "Reproduction by a second group",
  calibration: "Champion calibration",
  soak: "Soak test",
};

export default async function SubmissionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const v = await apiGetOrNull<View>(`/v1/submissions/${id}`);
  if (!v) {
    return (
      <Empty title="Submission not found">
        Check the link. Miners can also follow a submission with{" "}
        <Mono>ramcove-miner status</Mono>.
      </Empty>
    );
  }
  const measured = v.comparisons.filter((c) => c.status === "measured");
  return (
    <div className="min-w-0 space-y-8">
      <PageHeader
        eyebrow={<span className="num">{v.submission_id}</span>}
        title="Submission"
        actions={
          <>
            <AutoRefresh seconds={5} />
            <CopyRef
              value={v.support_ref}
              label={`Support ref ${v.support_ref}`}
            />
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <StatePill state={v.state} label={v.state_label} />
          {v.trusted_fixture && (
            <SimulatedTag what={`fixture: ${v.trusted_fixture}`} />
          )}
        </div>
      </PageHeader>

      {v.outcome.summary && (
        <Notice
          tone={
            v.state === "promoted"
              ? "ok"
              : v.outcome.code === "operator_failure"
                ? "warn"
                : "danger"
          }
          title={
            v.state === "promoted"
              ? "This submission is the champion"
              : v.outcome.code
                ? `Why it ended: ${v.outcome.code.replace(/_/g, " ")}`
                : "Outcome"
          }
        >
          {v.outcome.summary}
          {v.outcome.code && v.state !== "promoted" && (
            <p className="mt-1">
              <Link
                href={`/docs#outcome-${v.outcome.code}`}
                className="text-accent hover:underline"
              >
                What this outcome means, and what to do
              </Link>
            </p>
          )}
        </Notice>
      )}

      {v.registration_deadline && (
        <Notice
          tone="warn"
          title="Register the winning hotkey before this deadline"
        >
          The hotkey must be registered on the subnet by{" "}
          {when(v.registration_deadline)} (
          <TimeAgo at={v.registration_deadline} />
          ). If it is not, the submission ends unpromoted and the incumbent
          keeps the crown.
        </Notice>
      )}

      {v.state === "ready_for_promotion" &&
        v.blocking_submissions.length > 0 && (
          <Notice tone="info" title="Cleared, waiting for earlier admissions">
            {v.blocking_submissions.length} earlier submission(s) still
            hold priority. Promotion follows admission order, so finishing first
            does not move you ahead.
          </Notice>
        )}

      <div className="grid items-start gap-5 lg:grid-cols-[1.35fr_1fr]">
        <div className="space-y-5">
          <Card
            title="Progress"
            subtitle="Each stage, which worker ran it, and what it cost in GPU time."
          >
            {v.timeline.length === 0 ? (
              <Empty title="No work has started">
                Work starts once this submission joins the queue.
              </Empty>
            ) : (
              <ol className="space-y-3">
                {v.timeline.map((t, i) => (
                  <li key={i} className="flex gap-3">
                    <span
                      aria-hidden
                      className={
                        "mt-1.5 h-2 w-2 shrink-0 rounded-full " +
                        (t.status === "done"
                          ? "bg-ok"
                          : t.status === "leased"
                            ? "bg-accent"
                            : t.status === "failed" || t.status === "void"
                              ? "bg-danger"
                              : t.status === "cancelled"
                                ? "bg-warn"
                                : "bg-line-strong")
                      }
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-medium text-text">
                          {STAGE_TITLE[t.stage] ?? t.stage}
                        </span>
                        <Pill
                          tone={
                            t.status === "done"
                              ? "ok"
                              : t.status === "leased"
                                ? "accent"
                                : t.status === "queued"
                                  ? "neutral"
                                  : t.status === "cancelled"
                                    ? "warn"
                                    : "danger"
                          }
                        >
                          {t.status}
                        </Pill>
                        {t.champion_version !== null && (
                          <Pill tone="neutral">
                            vs champion v{t.champion_version}
                          </Pill>
                        )}
                        {t.attempts > 1 && (
                          <Pill tone="warn">attempt {t.attempts}</Pill>
                        )}
                      </div>
                      <div className="mt-0.5 text-[12px] text-muted">
                        {t.worker ? `worker ${t.worker} · ` : ""}
                        {<TimeAgo at={t.updated_at} />}
                        {t.gpu_centi_used
                          ? ` · ${centiHours(t.gpu_centi_used)} used`
                          : ""}
                        {t.lease_expires_at && t.status === "leased"
                          ? ` · lease ends ${when(t.lease_expires_at)}`
                          : ""}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>

          {measured.length > 0 && (
            <Card
              title="Capacity readings"
              subtitle={`Against the champion's fixed score. One reading decides, unless it lands between ${gain(v.margin_ppm, 0)} and ${gain(v.clear_win_ppm, 0)}: then a second reading does.`}
            >
              <Table
                head={[
                  "Reading",
                  "Challenger",
                  "Champion (fixed)",
                  "Gain",
                  "Worker",
                  "Seed round",
                ]}
              >
                {measured.map((c, i) => {
                  const ratio =
                    c.challenger_milli_rps && c.champion_milli_rps
                      ? (c.challenger_milli_rps / c.champion_milli_rps - 1) *
                        1e6
                      : null;
                  return (
                    <tr key={c.id}>
                      <Td>{i + 1}</Td>
                      <Td className="num">{rps(c.challenger_milli_rps)}</Td>
                      <Td className="num">{rps(c.champion_milli_rps)}</Td>
                      <Td className="num">{gain(ratio)}</Td>
                      <Td>{c.worker}</Td>
                      <Td className="num">
                        {c.beacon_round}{" "}
                        {c.beacon_simulated && (
                          <SimulatedTag what="dev beacon" />
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </Table>
              <p className="mt-3 text-[12px] leading-relaxed text-muted">
                Each reading generates fresh tests from a beacon round fixed in
                advance and finds the highest request rate the challenger
                sustains within the latency and quality limits. The
                champion&apos;s score was measured once, when it was crowned,
                and is not measured again.
              </p>
            </Card>
          )}

          {v.reports.length > 0 && (
            <Card
              title="Evidence"
              subtitle="Signed reports. Private source is never published."
            >
              {v.reports.map((r) => (
                <details
                  key={r.id}
                  className="border-b border-line py-2 last:border-0"
                >
                  <summary className="cursor-pointer text-[13px] text-text">
                    {STAGE_TITLE[r.kind] ?? r.kind} ·{" "}
                    <Mono>{shortHash(r.hash)}</Mono>{" "}
                    {r.simulated && <SimulatedTag />}
                  </summary>
                  {r.body ? (
                    <pre className="mt-2 max-h-96 overflow-auto rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-muted">
                      {JSON.stringify(r.body, null, 2)}
                    </pre>
                  ) : (
                    <p className="mt-2 text-[12px] text-muted">
                      This report is visible to the author, reviewers and the
                      operator.
                    </p>
                  )}
                </details>
              ))}
            </Card>
          )}

          {v.reviews.length > 0 && (
            <Card
              title="Review"
              subtitle="Only a flagged winner is reviewed. Flagged items are marked; a rejection must cite a failed criterion."
            >
              {v.reviews.map((r) => (
                <div
                  key={r.id}
                  className="border-b border-line py-3 last:border-0"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill
                      tone={
                        r.decision === "approve"
                          ? "ok"
                          : r.decision === "reject"
                            ? "danger"
                            : "info"
                      }
                    >
                      {r.decision ?? "open"}
                    </Pill>
                    <span className="text-[12px] text-muted">
                      {r.decided_at ? (
                        <>
                          {"decided "}
                          <TimeAgo at={r.decided_at} />
                        </>
                      ) : (
                        `due ${when(r.due_at)}`
                      )}
                    </span>
                  </div>
                  <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                    {r.criteria.map((c) => (
                      <li key={c.id} className="text-[12px] text-muted">
                        {c.passed === undefined ? "•" : c.passed ? "✓" : "✗"}{" "}
                        {c.title}
                        {c.flagged && (
                          <span className="ml-1.5">
                            <Pill tone="warn">flagged</Pill>
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                  {r.reasons && (
                    <p className="mt-2 text-[12px] leading-relaxed text-muted">
                      {r.reasons}
                    </p>
                  )}
                </div>
              ))}
            </Card>
          )}
        </div>

        <div className="space-y-5">
          <Card title="Result so far">
            <div className="grid grid-cols-2 gap-5">
              <Stat
                label="First reading"
                value={gain(v.first_gain_ppm)}
                hint="a close result gets a second"
              />
              <Stat
                label="Gain"
                value={gain(v.bound_gain_ppm)}
                tone={
                  v.bound_gain_ppm && v.bound_gain_ppm > v.margin_ppm
                    ? "ok"
                    : "default"
                }
                hint={`must exceed ${gain(v.margin_ppm, 0)}`}
              />
            </div>
            <div className="mt-4">
              <KeyValue
                rows={[
                  ["Admission", admissionKey(v.admission_key)],
                  [
                    "Admitted",
                    v.admitted_at ? when(v.admitted_at) : "not admitted",
                  ],
                  [
                    "Compared against",
                    v.compared_champion_version !== null
                      ? `champion v${v.compared_champion_version}`
                      : "—",
                  ],
                  ["Current champion", `v${v.current_champion_version}`],
                  ["Method", v.method ?? "—"],
                  ["Mechanism", v.mechanism?.replace(/_/g, " ") ?? "—"],
                ]}
              />
            </div>
          </Card>

          <Card title="What the states mean">
            <dl className="space-y-2 text-[12px] leading-relaxed text-muted">
              <div>
                <dt className="font-medium text-text">Screening</dt>
                <dd>
                  Isolated build and a short smoke check. It can only reject
                  decisively; it never judges speed.
                </dd>
              </div>
              <div>
                <dt className="font-medium text-text">Evaluation</dt>
                <dd>
                  Quality first, then capacity readings against the
                  champion&apos;s fixed score. A winner also passes the memory,
                  short-request, multi-turn and soak checks.
                </dd>
              </div>
              <div>
                <dt className="font-medium text-text">Review</dt>
                <dd>
                  Only when an automatic check flags a winner, for example
                  native code or third-party components. Otherwise promotion is
                  automatic.
                </dd>
              </div>
              <div>
                <dt className="font-medium text-text">Champion changed</dt>
                <dd>
                  If another submission is crowned while yours waits, your
                  measured gain is set against the new champion by arithmetic.
                  Nothing is measured again.
                </dd>
              </div>
            </dl>
          </Card>
        </div>
      </div>
      <p className="text-[12px] text-muted">
        <Link href="/dashboard#queue" className="text-accent hover:underline">
          ← Back to the queue
        </Link>
      </p>
    </div>
  );
}
