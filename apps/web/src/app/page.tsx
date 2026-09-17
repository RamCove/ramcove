import { AutoRefresh } from "@/components/client";
import { Card, Empty, KeyValue, Mono, Notice, Pill, SimulatedTag, Stat, Table, Td, Term } from "@/components/ui";
import { apiGetOrNull } from "@/lib/api";
import { ago, centiHours, gain, rps, usd, when } from "@/lib/format";
import Link from "next/link";

export const dynamic = "force-dynamic";

type Overview = {
  profile: { id: string; version: string; title: string; rule_hash: string; measured: boolean; bootstrap_mode: string };
  champion: {
    version: number;
    author: string | null;
    is_baseline: boolean;
    status: string;
    capacity_milli_rps: number | null;
    capacity_measured: boolean;
    bound_gain_ppm: number | null;
    explain: string;
  };
  champion_history: {
    version: number;
    author: string | null;
    status: string;
    capacity_milli_rps: number | null;
    bound_gain_ppm: number | null;
    promoted_at: string | null;
  }[];
  queue: { counts_by_state: Record<string, number>; admitted_active: number; waiting_list: number };
  capacity: {
    workers_ready: number;
    workers_total: number;
    committed_centi_gpu_hours: number;
    capacity_centi_gpu_hours: number;
    envelope_per_admission_centi: number;
    intake_paused: boolean;
    accepting_paid_submissions: boolean;
    reason: string;
    horizon_hours: number;
  };
  fee: { price_usd_micros?: number; price_simulated?: boolean; service_cost_usd_cents?: number; recovery_bp?: number };
  chain: { finalized_number: number; finalized_hash: string; simulated: boolean; observed_at: string } | null;
  incidents: { id: string; severity: string; title: string; summary: string }[];
};

export default async function OverviewPage() {
  const data = await apiGetOrNull<Overview>("/v1/overview");
  if (!data) {
    return <Empty title="No data yet">Start the API and the controller, then reload this page.</Empty>;
  }
  const { champion, capacity, queue, chain } = data;
  return (
    <div className="space-y-5">
      <section className="rounded-[var(--radius-card)] border border-line bg-surface px-5 py-6">
        <p className="text-[12px] font-medium uppercase tracking-[0.1em] text-accent">More AI. Same GPU.</p>
        <h1 className="mt-2 max-w-3xl text-[26px] font-semibold leading-tight tracking-tight">
          ROOM pays for software changes that let one fixed GPU serve more useful AI requests.
        </h1>
        <p className="mt-3 max-w-3xl text-[14px] leading-relaxed text-muted">
          Miners submit reviewable code. Validators build it in controlled environments and measure{" "}
          <Term term="qualified serving capacity" plain="The highest steady request rate where answers stay correct, fast enough and error-free" />{" "}
          against the current champion. One champion per profile holds the miner allocation until a challenger
          proves a real improvement and passes review.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Link
            href="/submit"
            className="rounded-[var(--radius-sm)] border border-accent bg-accent px-4 py-2 text-[13px] font-medium text-[#04201e] hover:bg-accent-strong"
          >
            Start a submission
          </Link>
          <Link
            href="/competition"
            className="rounded-[var(--radius-sm)] border border-line-strong bg-surface-2 px-4 py-2 text-[13px] font-medium text-text hover:bg-surface-3"
          >
            Explore the competition
          </Link>
        </div>
      </section>

      {data.incidents.length > 0 && (
        <div className="space-y-3">
          {data.incidents.map((i) => (
            <Notice key={i.id} tone={i.severity === "info" ? "info" : "warn"} title={i.title}>
              {i.summary}
            </Notice>
          ))}
        </div>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Card
          title="Current champion"
          subtitle={champion.explain}
          actions={<Link href="/competition" className="text-[13px] text-accent hover:underline">Details</Link>}
        >
          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Stat label="Version" value={`v${champion.version}`} hint={champion.is_baseline ? "tuned baseline" : "miner submission"} />
            <Stat
              label="Author"
              value={champion.author ?? "none"}
              hint={champion.is_baseline ? "earns nothing" : "receives the miner allocation"}
            />
            <Stat
              label={<>Capacity <span className="normal-case">(P-mem)</span></>}
              value={rps(champion.capacity_milli_rps)}
              tone="accent"
              hint={champion.capacity_measured ? "measured" : "simulated calibration"}
            />
            <Stat
              label="Confirmed gain"
              value={gain(champion.bound_gain_ppm)}
              hint="lower bound over paired blocks"
            />
          </div>
          <div className="mt-5">
            <h3 className="mb-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-faint">
              Approved capacity history
            </h3>
            <Table head={["Version", "Author", "Capacity", "Confirmed gain", "Status", "Promoted"]}
                   empty={data.champion_history.length === 0}>
              {data.champion_history.map((c) => (
                <tr key={c.version}>
                  <Td>v{c.version}</Td>
                  <Td>{c.author ?? <span className="text-faint">baseline</span>}</Td>
                  <Td className="num">{rps(c.capacity_milli_rps)}</Td>
                  <Td className="num">{gain(c.bound_gain_ppm)}</Td>
                  <Td>
                    <Pill tone={c.status === "current" ? "ok" : c.status === "rolled_back" ? "danger" : "neutral"}>
                      {c.status}
                    </Pill>
                  </Td>
                  <Td>{c.promoted_at ? ago(c.promoted_at) : "—"}</Td>
                </tr>
              ))}
            </Table>
          </div>
        </Card>

        <div className="space-y-5">
          <Card
            title="Evaluation capacity"
            subtitle="Paid admissions are capped by a conservative reservation, not by an average."
            actions={<AutoRefresh />}
          >
            <div className="grid grid-cols-2 gap-5">
              <Stat
                label="Workers ready"
                value={`${capacity.workers_ready} / ${capacity.workers_total}`}
                hint="safe and ready to evaluate"
                tone={capacity.workers_ready === 0 ? "warn" : "default"}
              />
              <Stat
                label="Reserved"
                value={centiHours(capacity.committed_centi_gpu_hours)}
                hint={`of ${centiHours(capacity.capacity_centi_gpu_hours)} over ${capacity.horizon_hours} h`}
              />
              <Stat label="Admitted, active" value={queue.admitted_active} hint="paid and in progress" />
              <Stat label="Waiting list" value={queue.waiting_list} hint="free, no fee taken" />
            </div>
            <div className="mt-4">
              {capacity.accepting_paid_submissions ? (
                <Notice tone="ok" title="Accepting paid submissions">
                  Each admission reserves {centiHours(capacity.envelope_per_admission_centi)} of worst-case work
                  until its outcome is known.
                </Notice>
              ) : (
                <Notice tone="warn" title="Paid admissions are paused">
                  {capacity.reason} You can still run the free checks and join the waiting list.
                </Notice>
              )}
            </div>
          </Card>

          <Card title="Chain and evidence" subtitle="What this build reads, and what it only proposes.">
            <KeyValue
              rows={[
                [
                  "Finalized block",
                  chain ? (
                    <span className="inline-flex items-center gap-2">
                      {chain.finalized_number} {chain.simulated && <SimulatedTag what="dev chain" />}
                    </span>
                  ) : (
                    "—"
                  ),
                ],
                ["Observed", chain ? ago(chain.observed_at) : "—"],
                ["Profile", <Mono key="p">{data.profile.id}@{data.profile.version}</Mono>],
                ["Rule hash", <Mono key="r">{data.profile.rule_hash.slice(0, 16)}…</Mono>],
                ["Bootstrap mode", data.profile.bootstrap_mode],
                [
                  "Fee basis",
                  data.fee.service_cost_usd_cents
                    ? `${usd(data.fee.service_cost_usd_cents)} service cost · ${(data.fee.recovery_bp ?? 0) / 100}% recovered`
                    : "—",
                ],
              ]}
            />
            <p className="mt-4 text-[12px] leading-relaxed text-muted">
              Weight plans are proposed only. Nothing is submitted to a chain in this build, and the champion
              never receives owner or validator emissions.
            </p>
          </Card>
        </div>
      </div>

      <Card title="How the competition works" subtitle="Four steps, with the money and the measurement kept apart.">
        <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["1. Free checks", "Format, signature, allowed paths, licences and duplicates are checked before anyone pays."],
            ["2. Reserve and pay", "When a slot exists you get a time-limited quote and pay a fee in TAO. Otherwise you wait free."],
            ["3. Measured", "Screening, then full evaluation, then five paired blocks against the frozen champion."],
            ["4. Reviewed", "People check code, licence and safety against published criteria before any crown changes."],
          ].map(([title, body]) => (
            <li key={title} className="rounded-[var(--radius-sm)] border border-line bg-surface-2 px-4 py-3">
              <p className="text-[13px] font-semibold text-text">{title}</p>
              <p className="mt-1 text-[12px] leading-relaxed text-muted">{body}</p>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
