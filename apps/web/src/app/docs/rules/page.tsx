import { Card, Empty, KeyValue, Mono, Notice, PageHeader, Pill, Stat, Table, Td, Term } from "@/components/ui";
import { DocsTabs } from "@/components/docs-tabs";
import { apiGetOrNull } from "@/lib/server-api";
import { centiHours, gain, rps, shortHash, usd, when } from "@/lib/format";
import type { Metadata } from "next";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Rules" };

type ProfileDetail = {
  profile: {
    profile_id: string;
    version: string;
    title: string;
    model: { repo: string; revision: string; license: string };
    engine: { repo: string; tag: string; commit: string; allowed_paths: string[]; forbidden_paths: string[] };
    hardware: { gpu: string; cpu_cores: number; vm_ram_gib: number; isolation: string; gpu_ceiling_margin_mib: number };
    workloads: string[];
    replacement: {
      delta_ppm: number;
      clear_win_ppm: number;
      grid_step_ppm: number;
      calibrated: boolean;
    };
    quality: {
      reference_id: string;
      vs_champion_margin_bp: number;
      vs_reference_margin_bp: number;
      absolute_min_accuracy_bp: Record<string, number>;
      length_ratio_vs_reference_bp: number;
    };
    latency: Record<string, number>;
    envelope: { screen: number; evaluation: number; winner_checks: number; recalibration_on_promotion: number };
    deadlines: Record<string, number>;
    fees: { service_cost_usd_cents_per_admission: number; recovery_bp: number; price_source: string };
    bootstrap: { mode: string; min_independent_validators_for_mainnet: number; quorum_validators_after_sunset: number };
    measured: boolean;
    no_winner_writer_verified: boolean;
  };
  rule_hash: string;
  champion: {
    version: number;
    author: string | null;
    artifact_sha256: string | null;
    attribution: { components?: { hotkey: string; lineage: string; method: string }[]; note?: string };
    status: string;
    capacity_milli_rps: number | null;
    capacity_measured: boolean;
    promoted_at: string | null;
    bound_gain_ppm: number | null;
  };
  weight_plan: {
    entries: { hotkey: string; uid: number; weight_u16: number; role: string }[];
    no_winner: boolean;
    notes: string[];
    writer_enabled: boolean;
    status: string;
    snapshot_block: number;
  } | null;
};

export default async function CompetitionPage() {
  const data = await apiGetOrNull<ProfileDetail>("/v1/profile");
  if (!data) return <Empty title="Profile unavailable">Start the API and reload.</Empty>;
  const p = data.profile;
  const r = p.replacement;
  return (
    <div className="min-w-0 space-y-8">
      <DocsTabs active="rules" />
      <PageHeader
        eyebrow={`Rules · ${p.title}`}
        title="Competition rules"
        lede="A profile fixes everything that affects a raw capacity number. Scores from different profiles never share a leaderboard, and every value below is a provisional planning value, not a measurement."
      >
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone="accent">
            {p.profile_id}@{p.version}
          </Pill>
          <Pill tone="neutral" title={data.rule_hash}>
            rule hash {shortHash(data.rule_hash)}
          </Pill>
          <Pill tone={p.measured ? "ok" : "warn"}>{p.measured ? "calibrated on hardware" : "not calibrated on hardware"}</Pill>
          <Pill tone="neutral">bootstrap: {p.bootstrap.mode}</Pill>
        </div>
      </PageHeader>

      {!p.measured && (
        <Notice tone="warn" title="Nothing here is measured on a real GPU">
          The thresholds, runtimes and costs come from the v0.2 whitepaper and its review. A Stage 1 noise
          study must replace them before real submissions are accepted.
        </Notice>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Card title="Current champion" subtitle="The complete stack that was actually tested.">
          <div className="grid grid-cols-2 gap-5">
            <Stat label="Version" value={`v${data.champion.version}`} />
            <Stat
              label="Capacity"
              value={rps(data.champion.capacity_milli_rps)}
              tone="accent"
              hint={data.champion.capacity_measured ? "measured" : "simulated calibration"}
            />
            <Stat label="Gain" value={gain(data.champion.bound_gain_ppm)} hint="over the previous champion" />
            <Stat label="Promoted" value={data.champion.promoted_at ? when(data.champion.promoted_at) : "—"} />
          </div>
          <div className="mt-4">
            <KeyValue
              rows={[
                ["Author", data.champion.author ?? "none (tuned baseline)"],
                ["Artifact", data.champion.artifact_sha256 ? <Mono key="a">{shortHash(data.champion.artifact_sha256)}</Mono> : "—"],
                ["Status", data.champion.status],
              ]}
            />
            {data.champion.attribution?.note && (
              <p className="mt-3 text-[12px] leading-relaxed text-muted">{data.champion.attribution.note}</p>
            )}
            {(data.champion.attribution?.components ?? []).length > 0 && (
              <div className="mt-3">
                <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">Attribution</h3>
                <ul className="mt-1 space-y-1 text-[13px] text-muted">
                  {data.champion.attribution.components!.map((c) => (
                    <li key={c.hotkey}>
                      <span className="text-text">{c.lineage}</span> · {c.method}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>

        <Card
          title="How a challenger replaces the champion"
          subtitle="One rule, published in advance and frozen with the profile version."
        >
          <div className="rounded-[var(--radius-sm)] border border-line bg-surface-2 px-4 py-3 font-mono text-[12px] leading-relaxed text-muted">
            G = capacity(challenger) / fixed score(champion) − 1<br />
            G ≤ δ: the champion stays · G ≥ {gain(r.clear_win_ppm, 0)}: the challenger wins
            <br />
            in between: one more reading; the average of the two must exceed δ<br />
            and a winner must pass every quality gate and winner check
          </div>
          <div className="mt-4 grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Stat label="Margin δ" value={gain(r.delta_ppm, 0)} />
            <Stat label="Clear win" value={gain(r.clear_win_ppm, 0)} hint="no second reading" />
            <Stat label="Readings" value="1–2" hint="per evaluation" />
            <Stat label="Rate grid" value={`${gain(r.grid_step_ppm, 0)}`} hint="step between rates" />
          </div>
          <p className="mt-4 text-[13px] leading-relaxed text-muted">
            Ties keep the incumbent. The champion&apos;s score is measured once per worker, when it is crowned, and
            never again. If another submission is crowned while a measured winner waits, the winner is set
            against the new champion by arithmetic, (1 + G) / (1 + G<sub>new</sub>) − 1: nothing is measured
            again and no new fee is charged. A person reviews a winner only when an automatic check flags it.{" "}
            {r.calibrated ? "" : "The margin, clear-win line and rate grid are uncalibrated until a noise study is published."}
          </p>
        </Card>

        <Card title="Fixed conditions" subtitle="Identical for the champion and every challenger.">
          <KeyValue
            rows={[
              ["Model", <Mono key="m">{p.model.repo}</Mono>],
              ["Model revision", <Mono key="mr">{shortHash(p.model.revision, 10)}</Mono>],
              ["Engine", <Mono key="e">{`${p.engine.repo} ${p.engine.tag}`}</Mono>],
              ["Engine commit", <Mono key="ec">{shortHash(p.engine.commit, 10)}</Mono>],
              ["GPU", p.hardware.gpu],
              ["Candidate VM", `${p.hardware.cpu_cores} cores · ${p.hardware.vm_ram_gib} GiB · no swap · no network`],
              ["GPU ceiling", `device memory − ${p.hardware.gpu_ceiling_margin_mib} MiB, sampled at the driver`],
              ["Isolation", p.hardware.isolation],
              ["Workloads", p.workloads.join(", ")],
              ["Model licence", p.model.license],
            ]}
          />
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">Allowed paths</h3>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-muted">
                {p.engine.allowed_paths.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">Forbidden paths</h3>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-muted">
                {p.engine.forbidden_paths.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          </div>
        </Card>

        <Card
          title="Quality and response-time gates"
          subtitle="A faster answer that is wrong or late never counts."
          className="lg:col-span-2"
        >
          <Table head={["Gate", "Value", "What it protects"]}>
            <tr>
              <Td>
                <Term term="TTFT" plain="Time until the first answer token reaches the user">
                  Time to first answer token
                </Term>
              </Td>
              <Td className="num">
                {p.latency.ttft_base_ms} ms + {p.latency.ttft_per_1k_prompt_ms} ms per 1k prompt tokens
              </Td>
              <Td>Users waiting before anything appears</Td>
            </tr>
            <tr>
              <Td>
                <Term term="TPOT" plain="Mean time between output tokens once the answer has started">
                  Mean time per output token
                </Term>
              </Td>
              <Td className="num">{p.latency.tpot_mean_ms} ms</Td>
              <Td>Answers that crawl</Td>
            </tr>
            <tr>
              <Td>Attainment</Td>
              <Td className="num">
                {p.latency.attainment_bp / 100}% per run · {p.latency.band_attainment_bp / 100}% per context band
              </Td>
              <Td>Long conversations pushed to the back</Td>
            </tr>
            <tr>
              <Td>Errors, rejections, deadline misses</Td>
              <Td className="num">≤ {p.latency.max_error_bp / 100}%</Td>
              <Td>Dropping work to look fast</Td>
            </tr>
            <tr>
              <Td>Quality vs the champion</Td>
              <Td className="num">lower bound above −{p.quality.vs_champion_margin_bp / 100} points</Td>
              <Td>Trading accuracy for speed</Td>
            </tr>
            <tr>
              <Td>Quality vs the frozen reference</Td>
              <Td className="num">lower bound above −{p.quality.vs_reference_margin_bp / 100} points</Td>
              <Td>Small losses adding up across generations</Td>
            </tr>
            <tr>
              <Td>Absolute floors</Td>
              <Td className="num">
                {Object.entries(p.quality.absolute_min_accuracy_bp)
                  .map(([k, v]) => `${k} ≥ ${v / 100}%`)
                  .join(" · ")}
              </Td>
              <Td>A floor no champion may cross</Td>
            </tr>
            <tr>
              <Td>Answer length</Td>
              <Td className="num">≥ {p.quality.length_ratio_vs_reference_bp / 100}% of the reference</Td>
              <Td>Shorter answers that score well</Td>
            </tr>
          </Table>
          <p className="mt-3 text-[12px] leading-relaxed text-muted">
            Quality reference: <Mono>{p.quality.reference_id}</Mono>
          </p>
        </Card>

        <Card
          title="GPU time per paid submission"
          subtitle="Booked: screening and one evaluation, released as results come in. Winners' extra checks and a new champion's score come from the reserve."
        >
          <Table head={["Work", "GPU time", "Who uses it"]}>
            <tr>
              <Td>screening</Td>
              <Td className="num whitespace-nowrap">{centiHours(p.envelope.screen)}</Td>
              <Td>booked for every paid submission</Td>
            </tr>
            <tr>
              <Td>evaluation</Td>
              <Td className="num whitespace-nowrap">{centiHours(p.envelope.evaluation)}</Td>
              <Td>booked for every paid submission</Td>
            </tr>
            <tr>
              <Td className="font-semibold">booked per submission</Td>
              <Td className="num whitespace-nowrap font-semibold">{centiHours(p.envelope.screen + p.envelope.evaluation)}</Td>
              <Td>counts toward the two-week queue</Td>
            </tr>
            <tr>
              <Td>winner checks</Td>
              <Td className="num whitespace-nowrap">{centiHours(p.envelope.winner_checks)}</Td>
              <Td>winners only, from the reserve</Td>
            </tr>
            <tr>
              <Td>new champion&apos;s score</Td>
              <Td className="num whitespace-nowrap">{centiHours(p.envelope.recalibration_on_promotion)}</Td>
              <Td>once per promotion, from the reserve</Td>
            </tr>
          </Table>
          <p className="mt-3 text-[12px] leading-relaxed text-muted">
            Fee basis: {usd(p.fees.service_cost_usd_cents_per_admission)} service cost per admission,{" "}
            {p.fees.recovery_bp / 100}% recovered from the miner, the rest subsidised by the operator. Price
            source <Mono>{p.fees.price_source}</Mono>.
          </p>
        </Card>

        <Card title="Proposed weight plan" subtitle="Deterministic from the approved champion. Never submitted in this build.">
          {data.weight_plan ? (
            <>
              <Table head={["Hotkey", "UID", "Weight", "Role"]}>
                {data.weight_plan.entries.map((e) => (
                  <tr key={`${e.hotkey}-${e.role}`}>
                    <Td>
                      <Mono>{shortHash(e.hotkey, 8)}</Mono>
                    </Td>
                    <Td className="num">{e.uid}</Td>
                    <Td className="num">{((e.weight_u16 / 65535) * 100).toFixed(1)}%</Td>
                    <Td>
                      <Pill tone={e.role === "champion" ? "ok" : "warn"}>{e.role.replace(/_/g, " ")}</Pill>
                    </Td>
                  </tr>
                ))}
              </Table>
              <div className="mt-3 space-y-2">
                <Pill tone="sim">status: {data.weight_plan.status.replace(/_/g, " ")}</Pill>{" "}
                <Pill tone={data.weight_plan.writer_enabled ? "ok" : "warn"}>
                  writer {data.weight_plan.writer_enabled ? "enabled" : "disabled"}
                </Pill>
                {data.weight_plan.notes.map((n) => (
                  <p key={n} className="text-[12px] leading-relaxed text-muted">
                    {n}
                  </p>
                ))}
                <p className="text-[12px] leading-relaxed text-muted">
                  Chain consensus and realized emissions can differ from a recommended vector. The champion
                  never receives the owner or validator shares.
                </p>
              </div>
            </>
          ) : (
            <Empty title="No weight plan yet">A plan is produced after the first promotion.</Empty>
          )}
        </Card>
      </div>
    </div>
  );
}
