import { AutoRefresh, CopyRef, TimeAgo } from "@/components/client";
import { Card, Empty, KeyValue, Mono, Notice, Pill, SimulatedTag, StatePill, Stat, Table, Td, Term } from "@/components/ui";
import { apiGetOrNull } from "@/lib/api";
import { admissionKey, centiHours, gain, rps, shortHash, tao, when } from "@/lib/format";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";
import { SubmissionActions } from "./actions";

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
  deadline_at: string | null;
  rebases_used: number;
  max_rebases: number;
  compared_champion_version: number | null;
  current_champion_version: number;
  triage_gain_ppm: number | null;
  bound_gain_ppm: number | null;
  margin_ppm: number;
  blocks_required: number;
  outcome: { code: string | null; summary: string | null; fee: string | null };
  method: string | null;
  mechanism: string | null;
  trusted_fixture: string | null;
  changed_paths: string[] | null;
  artifact_sha256: string | null;
  blocking_submissions: string[];
  timeline: {
    stage: string;
    status: string;
    block_no: number | null;
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
    criteria: { id: string; title: string; passed?: boolean }[];
    reasons: string | null;
    due_at: string;
    decided_at: string | null;
  }[];
  appeals: { id: string; status: string; kind: string; grounds: string; decision_reason: string | null; due_at: string }[];
  reports: { id: string; kind: string; hash: string; simulated: boolean; body: Record<string, unknown> | null; created_at: string }[];
  quote?: { id: string; amount_rao: number; status: string; expires_block: number; recipient: string; payer: string };
  receipt?: { id: string; body: Record<string, unknown>; signature: string; signer: string };
  credits?: { id: string; amount_rao: number; reason: string; expires_at: string }[];
  refunds?: { id: string; amount_rao: number; status: string; reason: string }[];
};

const STAGE_TITLE: Record<string, string> = {
  screen: "Screening",
  full: "Full evaluation",
  confirm_block: "Confirmation block",
  calibration: "Champion calibration",
  soak: "Soak test",
};

export default async function SubmissionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const cookie = (await cookies()).toString();
  const v = await apiGetOrNull<View>(`/v1/submissions/${id}`, cookie);
  if (!v) return <Empty title="Submission not found">Check the link, or sign in if this submission is yours.</Empty>;
  const owner = Boolean(v.artifact_sha256);
  const measured = v.comparisons.filter((c) => c.status === "measured");
  return (
    <div className="min-w-0 space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[20px] font-semibold tracking-tight">Submission</h1>
            <StatePill state={v.state} label={v.state_label} />
            {v.trusted_fixture && <SimulatedTag what={`fixture: ${v.trusted_fixture}`} />}
          </div>
          <p className="num mt-1 font-mono text-[12px] text-muted">{v.submission_id}</p>
        </div>
        <div className="flex items-center gap-2">
          <AutoRefresh seconds={5} />
          <CopyRef value={v.support_ref} label={`Support ref ${v.support_ref}`} />
        </div>
      </header>

      {v.outcome.summary && (
        <Notice
          tone={v.state === "promoted" ? "ok" : v.outcome.fee === "refund_or_credit" ? "warn" : "danger"}
          title={
            v.state === "promoted"
              ? "This submission is the champion"
              : v.outcome.code
                ? `Why it ended: ${v.outcome.code.replace(/_/g, " ")}`
                : "Outcome"
          }
        >
          {v.outcome.summary}
          {v.outcome.fee && (
            <p className="mt-1">
              Fee: <strong>{v.outcome.fee.replace(/_/g, " ")}</strong>
              {v.outcome.fee === "refund_or_credit" && " — you were not charged for an operator-side failure."}
            </p>
          )}
        </Notice>
      )}

      {v.state === "ready_for_promotion" && v.blocking_submissions.length > 0 && (
        <Notice tone="info" title="Approved, waiting for earlier admissions">
          {v.blocking_submissions.length} earlier paid submission(s) still hold priority. Promotion follows
          admission order, so finishing first does not move you ahead.
        </Notice>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[1.35fr_1fr]">
        <div className="space-y-5">
          <Card title="Progress" subtitle="Each stage, which worker ran it, and what it cost in GPU time.">
            {v.timeline.length === 0 ? (
              <Empty title="No work has started">Work starts once a finalized payment admits this submission.</Empty>
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
                          {t.block_no !== null && ` ${t.block_no + 1}`}
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
                        {t.champion_version !== null && <Pill tone="neutral">vs champion v{t.champion_version}</Pill>}
                        {t.attempts > 1 && <Pill tone="warn">attempt {t.attempts}</Pill>}
                      </div>
                      <div className="mt-0.5 text-[12px] text-muted">
                        {t.worker ? `worker ${t.worker} · ` : ""}
                        {<TimeAgo at={t.updated_at} />}
                        {t.gpu_centi_used ? ` · ${centiHours(t.gpu_centi_used)} used` : ""}
                        {t.lease_expires_at && t.status === "leased" ? ` · lease ends ${when(t.lease_expires_at)}` : ""}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Card>

          {measured.length > 0 && (
            <Card
              title="Confirmation blocks"
              subtitle={`Paired measurements against the frozen champion. ${v.blocks_required} are required.`}
            >
              <Table head={["Block", "Challenger", "Champion", "Ratio", "Worker", "Seed round"]}>
                {measured.map((c, i) => {
                  const ratio =
                    c.challenger_milli_rps && c.champion_milli_rps
                      ? (c.challenger_milli_rps / c.champion_milli_rps - 1) * 1e6
                      : null;
                  return (
                    <tr key={c.id}>
                      <Td>{i + 1}</Td>
                      <Td className="num">{rps(c.challenger_milli_rps)}</Td>
                      <Td className="num">{rps(c.champion_milli_rps)}</Td>
                      <Td className="num">{gain(ratio)}</Td>
                      <Td>{c.worker}</Td>
                      <Td className="num">
                        {c.beacon_round} {c.beacon_simulated && <SimulatedTag what="dev beacon" />}
                      </Td>
                    </tr>
                  );
                })}
              </Table>
              <p className="mt-3 text-[12px] leading-relaxed text-muted">
                Each block re-images a worker, generates fresh tests from a beacon round fixed in advance, and
                measures both stacks on the same tests. The decision uses a conservative lower bound over the
                blocks, not the best block.
              </p>
            </Card>
          )}

          {v.reports.length > 0 && (
            <Card title="Evidence" subtitle="Signed reports. Private source is never published.">
              {v.reports.map((r) => (
                <details key={r.id} className="border-b border-line py-2 last:border-0">
                  <summary className="cursor-pointer text-[13px] text-text">
                    {STAGE_TITLE[r.kind] ?? r.kind} · <Mono>{shortHash(r.hash)}</Mono>{" "}
                    {r.simulated && <SimulatedTag />}
                  </summary>
                  {r.body ? (
                    <pre className="mt-2 max-h-96 overflow-auto rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-muted">
                      {JSON.stringify(r.body, null, 2)}
                    </pre>
                  ) : (
                    <p className="mt-2 text-[12px] text-muted">
                      This report is visible to the author, reviewers and the operator.
                    </p>
                  )}
                </details>
              ))}
            </Card>
          )}

          {v.reviews.length > 0 && (
            <Card title="Review" subtitle="Published criteria; a rejection must cite a failed criterion.">
              {v.reviews.map((r) => (
                <div key={r.id} className="border-b border-line py-3 last:border-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={r.decision === "approve" ? "ok" : r.decision === "reject" ? "danger" : "info"}>
                      {r.decision ?? "open"}
                    </Pill>
                    <span className="text-[12px] text-muted">
                      {r.decided_at ? <>{"decided "}<TimeAgo at={r.decided_at} /></> : `due ${when(r.due_at)}`}
                    </span>
                  </div>
                  <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                    {r.criteria.map((c) => (
                      <li key={c.id} className="text-[12px] text-muted">
                        {c.passed === undefined ? "•" : c.passed ? "✓" : "✗"} {c.title}
                      </li>
                    ))}
                  </ul>
                  {r.reasons && <p className="mt-2 text-[12px] leading-relaxed text-muted">{r.reasons}</p>}
                </div>
              ))}
            </Card>
          )}
        </div>

        <div className="space-y-5">
          <Card title="Result so far">
            <div className="grid grid-cols-2 gap-5">
              <Stat label="Triage gain" value={gain(v.triage_gain_ppm)} hint="single estimate, not promotion evidence" />
              <Stat
                label="Confirmed bound"
                value={gain(v.bound_gain_ppm)}
                tone={v.bound_gain_ppm && v.bound_gain_ppm > v.margin_ppm ? "ok" : "default"}
                hint={`must exceed ${gain(v.margin_ppm, 0)}`}
              />
            </div>
            <div className="mt-4">
              <KeyValue
                rows={[
                  ["Admission", admissionKey(v.admission_key)],
                  ["Admitted", v.admitted_at ? when(v.admitted_at) : "not admitted"],
                  ["Service deadline", v.deadline_at ? when(v.deadline_at) : "—"],
                  ["Compared against", v.compared_champion_version !== null ? `champion v${v.compared_champion_version}` : "—"],
                  ["Current champion", `v${v.current_champion_version}`],
                  ["Rebases used", `${v.rebases_used} of ${v.max_rebases}`],
                  ["Method", v.method ?? "—"],
                  ["Mechanism", v.mechanism?.replace(/_/g, " ") ?? "—"],
                ]}
              />
            </div>
          </Card>

          {owner && (
            <Card title="Your payment" subtitle="Visible only to you and the operator.">
              <KeyValue
                rows={[
                  ["Quote", v.quote ? `${tao(v.quote.amount_rao)} TAO · ${v.quote.status}` : "—"],
                  ["Receipt", v.receipt ? <Mono key="r">{v.receipt.id}</Mono> : "not issued"],
                  ["Signed by", v.receipt ? <Mono key="s">{shortHash(v.receipt.signer, 8)}</Mono> : "—"],
                  ["Artifact", <Mono key="a">{shortHash(v.artifact_sha256, 12)}</Mono>],
                ]}
              />
              {(v.credits ?? []).length > 0 && (
                <div className="mt-3">
                  <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">Credits</h3>
                  {v.credits!.map((c) => (
                    <p key={c.id} className="text-[12px] text-muted">
                      {tao(c.amount_rao)} TAO — {c.reason}
                    </p>
                  ))}
                </div>
              )}
              {(v.refunds ?? []).length > 0 && (
                <div className="mt-3">
                  <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">Refunds</h3>
                  {v.refunds!.map((r) => (
                    <p key={r.id} className="text-[12px] text-muted">
                      {tao(r.amount_rao)} TAO — {r.status} · {r.reason}
                    </p>
                  ))}
                </div>
              )}
              {v.changed_paths && (
                <div className="mt-3">
                  <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">Changed paths</h3>
                  <ul className="mt-1 font-mono text-[11px] text-muted">
                    {v.changed_paths.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>
          )}

          {owner && <SubmissionActions submissionId={v.submission_id} state={v.state} />}

          <Card title="What the states mean">
            <dl className="space-y-2 text-[12px] leading-relaxed text-muted">
              <div>
                <dt className="font-medium text-text">Screening</dt>
                <dd>Isolated build and a short smoke check. It can only reject decisively; it never judges speed.</dd>
              </div>
              <div>
                <dt className="font-medium text-text">Full evaluation</dt>
                <dd>
                  Quality first, then a capacity search, memory evidence, the short-request control and a
                  multi-turn check with real answers.
                </dd>
              </div>
              <div>
                <dt className="font-medium text-text">Confirmation</dt>
                <dd>{v.blocks_required} fresh paired blocks against the frozen champion, on separately provisioned workers.</dd>
              </div>
              <div>
                <dt className="font-medium text-text">Rebase</dt>
                <dd>
                  The champion changed during your evaluation, so the comparison is repeated against the new
                  champion. You keep your place and pay no new fee.
                </dd>
              </div>
            </dl>
          </Card>
        </div>
      </div>
      <p className="text-[12px] text-muted">
        <Link href="/queue" className="text-accent hover:underline">
          ← Back to the queue
        </Link>
      </p>
    </div>
  );
}
