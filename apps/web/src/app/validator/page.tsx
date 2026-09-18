import { AutoRefresh, TimeAgo } from "@/components/client";
import { Card, Empty, KeyValue, Mono, Notice, Pill, SimulatedTag, Stat, Table, Td } from "@/components/ui";
import { apiGetOrNull } from "@/lib/api";
import { gain, rps, when } from "@/lib/format";
import type { Metadata } from "next";
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Validator" };

type Workspace = {
  validator: {
    hotkey: string;
    name: string;
    scoring: boolean;
    operator_affiliated: boolean;
    independence_group: string;
    stake_share_bp: number | null;
  } | null;
  workers: {
    id: string;
    provider: string;
    online: boolean;
    safe_and_ready: boolean;
    readiness: { checks?: { id: string; ok: boolean; detail: string }[]; untrusted_code_isolation?: boolean; simulated?: boolean; calibration?: { capacity_milli_rps: number; tight_capacity_milli_rps: number; flag: string } };
    calibrated_champion_version: number | null;
    calibrated_at: string | null;
    calibration_current: boolean;
    enabled: boolean;
  }[];
  queue: {
    job_id: string;
    stage: string;
    status: string;
    submission_id: string | null;
    priority: [number, number];
    lease_worker: string | null;
    lease_expires_at: string | null;
  }[];
  comparisons: {
    id: string;
    submission_id: string;
    status: string;
    champion_version: number;
    beacon_round: number;
    worker: string;
    challenger_milli_rps: number | null;
    champion_milli_rps: number | null;
  }[];
  chain: { finalized_number: number; simulated: boolean; observed_at: string; genesis_hash: string } | null;
  reimbursement_note: string;
};

export default async function ValidatorPage() {
  const cookie = (await cookies()).toString();
  const ws = await apiGetOrNull<Workspace>("/v1/validator/workspace", cookie);
  if (!ws) {
    return (
      <Card title="Validator workspace">
        <Empty title="Sign in as a validator">
          This page needs the validator role. In this local build you can sign in as the demo bootstrap
          validator.
        </Empty>
      </Card>
    );
  }
  if (!ws.validator) return <Empty title="This hotkey is not a registered validator" />;
  const ready = ws.workers.filter((w) => w.safe_and_ready).length;
  return (
    <div className="min-w-0 space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">{ws.validator.name}</h1>
          <p className="num mt-1 font-mono text-[12px] text-muted">{ws.validator.hotkey}</p>
        </div>
        <AutoRefresh seconds={5} />
      </header>

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <Stat label="Workers online" value={ws.workers.filter((w) => w.online).length} hint="recent heartbeat" />
        </Card>
        <Card>
          <Stat
            label="Safe and ready"
            value={ready}
            tone={ready === 0 ? "warn" : "ok"}
            hint="isolation checks passed"
          />
        </Card>
        <Card>
          <Stat label="Scoring validator" value={ws.validator.scoring ? "yes" : "no"} hint={ws.validator.independence_group} />
        </Card>
        <Card>
          <Stat
            label="Chain"
            value={ws.chain ? `#${ws.chain.finalized_number}` : "—"}
            hint={
              ws.chain ? (
                <>
                  {ws.chain.simulated ? "dev chain · " : ""}
                  <TimeAgo at={ws.chain.observed_at} />
                </>
              ) : (
                "unknown"
              )
            }
          />
        </Card>
      </div>

      {ws.validator.operator_affiliated && (
        <Notice tone="warn" title="Operator-affiliated validator">
          Workers run by one party are parallel, not independent. During bootstrap the operator&apos;s own
          measurements decide promotions; that is a trust assumption, not a verification.
        </Notice>
      )}

      <Card title="Workers" subtitle="Online means a heartbeat arrived. Safe and ready means the isolation checks passed.">
        {ws.workers.length === 0 ? (
          <Empty title="No workers registered" />
        ) : (
          <div className="space-y-4">
            {ws.workers.map((w) => (
              <div key={w.id} className="rounded-[var(--radius-sm)] border border-line bg-surface-2 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[14px] font-medium text-text">{w.id}</span>
                  <Pill tone={w.online ? "ok" : "warn"}>{w.online ? "online" : "offline"}</Pill>
                  <Pill tone={w.safe_and_ready ? "ok" : "danger"}>
                    {w.safe_and_ready ? "safe and ready" : "not ready to evaluate"}
                  </Pill>
                  {w.readiness.simulated && <SimulatedTag what="simulated provider" />}
                  <Pill tone={w.readiness.untrusted_code_isolation ? "ok" : "warn"}>
                    {w.readiness.untrusted_code_isolation ? "untrusted code isolated" : "trusted fixtures only"}
                  </Pill>
                  <Pill tone={w.calibration_current ? "ok" : "warn"}>
                    {w.calibration_current ? "calibration current" : "needs calibration"}
                  </Pill>
                </div>
                <div className="mt-3">
                  <KeyValue
                    rows={[
                      ["Provider", <Mono key="p">{w.provider}</Mono>],
                      ["Calibrated", w.calibrated_at ? <><TimeAgo at={w.calibrated_at} />{" (champion v${w.calibrated_champion_version})"}</> : "never"],
                      [
                        "Calibrated capacity",
                        w.readiness.calibration ? rps(w.readiness.calibration.capacity_milli_rps) : "—",
                      ],
                      [
                        "Tighter budget",
                        w.readiness.calibration ? rps(w.readiness.calibration.tight_capacity_milli_rps) : "—",
                      ],
                    ]}
                  />
                </div>
                {w.readiness.checks && (
                  <ul className="mt-3 space-y-1">
                    {w.readiness.checks.map((c) => (
                      <li key={c.id} className="text-[12px] text-muted">
                        <span className={c.ok ? "text-ok" : "text-danger"}>{c.ok ? "✓" : "✗"}</span> {c.id}:{" "}
                        {c.detail}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Card title="Work queue" subtitle="Leases are ordered by admission key across the whole profile.">
          {ws.queue.length === 0 ? (
            <Empty title="No queued or leased jobs" />
          ) : (
            <Table head={["Stage", "Status", "Submission", "Priority", "Worker", "Lease ends"]}>
              {ws.queue.map((j) => (
                <tr key={j.job_id}>
                  <Td>{j.stage.replace(/_/g, " ")}</Td>
                  <Td>
                    <Pill tone={j.status === "leased" ? "accent" : "neutral"}>{j.status}</Pill>
                  </Td>
                  <Td>{j.submission_id ? `${j.submission_id.slice(0, 12)}…` : <span className="text-faint">—</span>}</Td>
                  <Td className="num">
                    {j.priority[0]}·{j.priority[1]}
                  </Td>
                  <Td>{j.lease_worker ?? "—"}</Td>
                  <Td>{j.lease_expires_at ? when(j.lease_expires_at) : "—"}</Td>
                </tr>
              ))}
            </Table>
          )}
        </Card>

        <Card title="Recent comparisons" subtitle="Each block records its anchor, beacon round and both readings.">
          {ws.comparisons.length === 0 ? (
            <Empty title="No comparisons yet" />
          ) : (
            <Table head={["Submission", "Champion", "Challenger", "Gain", "Status", "Round"]}>
              {ws.comparisons.map((c) => (
                <tr key={c.id}>
                  <Td>{c.submission_id.slice(0, 12)}…</Td>
                  <Td className="num">{rps(c.champion_milli_rps)}</Td>
                  <Td className="num">{rps(c.challenger_milli_rps)}</Td>
                  <Td className="num">
                    {gain(
                      c.challenger_milli_rps && c.champion_milli_rps
                        ? (c.challenger_milli_rps / c.champion_milli_rps - 1) * 1e6
                        : null,
                    )}
                  </Td>
                  <Td>
                    <Pill tone={c.status === "measured" ? "ok" : c.status === "void" ? "danger" : "neutral"}>
                      {c.status}
                    </Pill>
                  </Td>
                  <Td className="num">{c.beacon_round}</Td>
                </tr>
              ))}
            </Table>
          )}
          <p className="mt-3 text-[12px] leading-relaxed text-muted">{ws.reimbursement_note}</p>
        </Card>
      </div>
    </div>
  );
}
