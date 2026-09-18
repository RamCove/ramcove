import { AutoRefresh, TimeAgo } from "@/components/client";
import { Card, Empty, Mono, Notice, PageHeader, Pill, Stat, Table, Td } from "@/components/ui";
import { apiGetOrNull } from "@/lib/api";
import { centiHours, tao, when } from "@/lib/format";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { OperatorControls, RefundControls } from "./controls";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Operator" };

type Console = {
  intake: { paused: boolean; committed_centi: number; envelope_per_admission_centi: number };
  submissions_by_state: Record<string, number>;
  queued_jobs: Record<string, number>;
  leases: {
    job_id: string;
    stage: string;
    worker: string | null;
    submission_id: string | null;
    expires_at: string | null;
    attempts: number;
    expired: boolean;
  }[];
  open_quotes: { id: string; submission_id: string; amount_rao: number; expires_block: number; hotkey: string }[];
  refunds: { id: string; status: string; amount_rao: number; hotkey: string; reason: string; submission_id: string | null; simulated: boolean }[];
  credits: { id: string; hotkey: string; amount_rao: number; reason: string; expires_at: string; consumed_by: string | null }[];
  ledger_totals: { kind: string; total_rao: number; entries: number }[];
  open_reviews: { id: string; submission_id: string; due_at: string; overdue: boolean }[];
  incidents: { id: string; severity: string; title: string; summary: string; started_at: string; resolved_at: string | null }[];
  profile_versions: { profile_id: string; version: string; rule_hash: string; active: boolean; published_at: string }[];
  workers: { id: string; validator: string; ready: boolean; enabled: boolean; calibrated_champion_version: number | null }[];
  guardrails: string[];
};

export default async function OperatorPage() {
  const cookie = (await cookies()).toString();
  const [data, audit] = await Promise.all([
    apiGetOrNull<Console>("/v1/operator/console", cookie),
    apiGetOrNull<{ items: { id: number; at: string; actor: string; action: string; subject_type: string; subject_id: string }[] }>(
      "/v1/operator/audit",
      cookie,
    ),
  ]);
  if (!data) {
    return (
      <Card title="Operator console">
        <Empty title="Sign in as the operator">This console needs the operator role.</Empty>
      </Card>
    );
  }
  return (
    <div className="min-w-0 space-y-8">
      <PageHeader
        eyebrow="Operator"
        title="Operator console"
        lede="Admissions, capacity, leases, money and evidence. No control here crowns a champion by hand."
        actions={<AutoRefresh seconds={5} />}
      />

      <Notice tone="info" title="Guardrails">
        <ul className="mt-1 list-disc space-y-1 pl-5">
          {data.guardrails.map((g) => (
            <li key={g}>{g}</li>
          ))}
        </ul>
      </Notice>

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <Stat
            label="Intake"
            value={data.intake.paused ? "paused" : "open"}
            tone={data.intake.paused ? "warn" : "ok"}
            hint="paid admissions"
          />
        </Card>
        <Card>
          <Stat label="Reserved work" value={centiHours(data.intake.committed_centi)} hint="worst case, not average" />
        </Card>
        <Card>
          <Stat
            label="Expired leases"
            value={data.leases.filter((l) => l.expired).length}
            tone={data.leases.some((l) => l.expired) ? "warn" : "default"}
            hint="swept by the controller"
          />
        </Card>
        <Card>
          <Stat
            label="Overdue reviews"
            value={data.open_reviews.filter((r) => r.overdue).length}
            tone={data.open_reviews.some((r) => r.overdue) ? "warn" : "default"}
            hint={`${data.open_reviews.length} open`}
          />
        </Card>
      </div>

      <OperatorControls paused={data.intake.paused} />

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Card title="Queue health">
          <Table head={["State", "Submissions"]}>
            {Object.entries(data.submissions_by_state).map(([s, n]) => (
              <tr key={s}>
                <Td>{s.replace(/_/g, " ")}</Td>
                <Td className="num">{n}</Td>
              </tr>
            ))}
          </Table>
          <h3 className="mt-4 text-[12px] font-semibold uppercase tracking-[0.06em] text-faint">Queued jobs</h3>
          <Table head={["Stage", "Queued"]}>
            {Object.entries(data.queued_jobs).map(([s, n]) => (
              <tr key={s}>
                <Td>{s.replace(/_/g, " ")}</Td>
                <Td className="num">{n}</Td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title="Leases" subtitle="A lease expiry requeues the job and keeps its admission priority.">
          {data.leases.length === 0 ? (
            <Empty title="No active leases" />
          ) : (
            <Table head={["Job", "Stage", "Worker", "Attempts", "Expires"]}>
              {data.leases.map((l) => (
                <tr key={l.job_id}>
                  <Td>{l.job_id.slice(0, 12)}…</Td>
                  <Td>{l.stage.replace(/_/g, " ")}</Td>
                  <Td>{l.worker ?? "—"}</Td>
                  <Td className="num">{l.attempts}</Td>
                  <Td>
                    {l.expired ? <Pill tone="danger">expired</Pill> : when(l.expires_at)}
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Money" subtitle="Fees, credits and refund liabilities are separate records.">
          <Table head={["Record", "Entries", "Total"]}>
            {data.ledger_totals.map((t) => (
              <tr key={t.kind}>
                <Td>{t.kind.replace(/_/g, " ")}</Td>
                <Td className="num">{t.entries}</Td>
                <Td className="num">{tao(t.total_rao)} TAO</Td>
              </tr>
            ))}
          </Table>
          <h3 className="mt-4 text-[12px] font-semibold uppercase tracking-[0.06em] text-faint">Refunds</h3>
          {data.refunds.length === 0 ? (
            <p className="mt-1 text-[13px] text-muted">No refunds requested.</p>
          ) : (
            <RefundControls refunds={data.refunds} />
          )}
          <h3 className="mt-4 text-[12px] font-semibold uppercase tracking-[0.06em] text-faint">Credits</h3>
          {data.credits.length === 0 ? (
            <p className="mt-1 text-[13px] text-muted">No credits issued.</p>
          ) : (
            <Table head={["Hotkey", "Amount", "Reason", "Expires", "Used"]}>
              {data.credits.map((c) => (
                <tr key={c.id}>
                  <Td>{c.hotkey.slice(0, 10)}…</Td>
                  <Td className="num">{tao(c.amount_rao)}</Td>
                  <Td className="max-w-xs text-[12px] text-muted">{c.reason}</Td>
                  <Td>{when(c.expires_at)}</Td>
                  <Td>{c.consumed_by ? "yes" : "no"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Versioned configuration" subtitle="A profile version is immutable; its hash is recorded with every decision.">
          <Table head={["Profile", "Version", "Rule hash", "Active", "Published"]}>
            {data.profile_versions.map((v) => (
              <tr key={`${v.profile_id}-${v.version}`}>
                <Td>{v.profile_id}</Td>
                <Td>{v.version}</Td>
                <Td>
                  <Mono>{v.rule_hash.slice(0, 14)}…</Mono>
                </Td>
                <Td>{v.active ? <Pill tone="ok">active</Pill> : <Pill tone="neutral">retired</Pill>}</Td>
                <Td>{<TimeAgo at={v.published_at} />}</Td>
              </tr>
            ))}
          </Table>
          <h3 className="mt-4 text-[12px] font-semibold uppercase tracking-[0.06em] text-faint">Workers</h3>
          <Table head={["Worker", "Validator", "Ready", "Enabled", "Calibrated for"]}>
            {data.workers.map((w) => (
              <tr key={w.id}>
                <Td>{w.id}</Td>
                <Td>{w.validator.slice(0, 10)}…</Td>
                <Td>{w.ready ? <Pill tone="ok">ready</Pill> : <Pill tone="warn">not ready</Pill>}</Td>
                <Td>{w.enabled ? "yes" : "no"}</Td>
                <Td className="num">{w.calibrated_champion_version ?? "—"}</Td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title="Incidents">
          {data.incidents.length === 0 ? (
            <Empty title="No incidents recorded" />
          ) : (
            <ul className="space-y-2">
              {data.incidents.map((i) => (
                <li key={i.id} className="rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={i.severity === "critical" || i.severity === "major" ? "danger" : i.severity === "minor" ? "warn" : "info"}>
                      {i.severity}
                    </Pill>
                    <span className="text-[13px] font-medium text-text">{i.title}</span>
                    {i.resolved_at ? <Pill tone="ok">resolved</Pill> : <Pill tone="warn">open</Pill>}
                  </div>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">{i.summary}</p>
                  <p className="mt-1 text-[11px] text-faint">started {<TimeAgo at={i.started_at} />}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Audit trail" subtitle="Append-only and hash-chained. Verify it from the controls above.">
          {!audit || audit.items.length === 0 ? (
            <Empty title="No audit events" />
          ) : (
            <Table head={["When", "Actor", "Action", "Subject"]}>
              {audit.items.slice(0, 25).map((e) => (
                <tr key={e.id}>
                  <Td>{<TimeAgo at={e.at} />}</Td>
                  <Td>{e.actor.length > 14 ? `${e.actor.slice(0, 12)}…` : e.actor}</Td>
                  <Td>{e.action.replace(/_/g, " ")}</Td>
                  <Td>
                    <span className="text-[12px] text-muted">
                      {e.subject_type} {e.subject_id.slice(0, 14)}
                    </span>
                  </Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      </div>
    </div>
  );
}
