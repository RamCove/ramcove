import {
  Card,
  Empty,
  KeyValue,
  Mono,
  Notice,
  PageHeader,
  Pill,
  Stat,
  Table,
  Td,
  Term,
} from "@/components/ui";
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
    model: {
      repo: string;
      revision: string;
      license: string;
      mode?: string;
      max_model_len?: number;
      decoding?: string;
    };
    evaluator?: { version: string; weights_version_key: number };
    engine: {
      repo: string;
      tag: string;
      commit: string;
      allowed_paths: string[];
      forbidden_paths: string[];
      torch?: string | null;
      cuda?: string | null;
      args_sha256?: string | null;
    };
    hardware: {
      gpu: string;
      cpu_cores: number;
      vm_ram_gib: number;
      isolation: string;
      gpu_ceiling_margin_mib: number;
    };
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
      vs_champion_stratum_margin_bp: number;
      vs_reference_margin_bp: number;
      absolute_min_accuracy_bp: Record<string, number>;
      length_ratio_vs_reference_bp: number;
    };
    latency: Record<string, number>;
    envelope: {
      screen: number;
      evaluation: number;
      winner_checks: number;
      recalibration_on_promotion: number;
      champion_answers_per_bank: number;
    };
    deadlines: Record<string, number>;
    // older snapshots name this "bootstrap"
    deployment?: { mode: string; reproduce_winners: boolean };
    bootstrap?: { mode: string };
    measured: boolean;
    no_winner_writer_verified: boolean;
  };
  rule_hash: string;
  champion: {
    version: number;
    author: string | null;
    artifact_sha256: string | null;
    attribution: {
      components?: { hotkey: string; lineage: string; method: string }[];
      note?: string;
    };
    status: string;
    capacity_milli_rps: number | null;
    capacity_measured: boolean;
    promoted_at: string | null;
    bound_gain_ppm: number | null;
  };
  weight_plan: {
    no_winner: boolean;
    notes: string[];
    writer_enabled: boolean;
    status: string;
    snapshot_block: number;
  } | null;
};

type QuestionBanks = {
  rule: {
    period_days: number;
    screening_long: number;
    screening_general: number;
    offline_long: number;
    offline_general: number;
  };
  banks: {
    bank_id: string;
    period_index: number;
    starts_at: string;
    ends_at: string;
    commitment: string;
    status: "current" | "upcoming" | "ended" | "revealed";
    revealed_seed: string | null;
  }[];
};

export default async function CompetitionPage() {
  const [data, qb] = await Promise.all([
    apiGetOrNull<ProfileDetail>("/v1/profile"),
    apiGetOrNull<QuestionBanks>("/v1/question-banks"),
  ]);
  if (!data)
    return <Empty title="Profile unavailable">Start the API and reload.</Empty>;
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
          <Pill tone={p.measured ? "ok" : "warn"}>
            {p.measured
              ? "calibrated on hardware"
              : "not calibrated on hardware"}
          </Pill>
          <Pill tone="neutral">
            deployment: {(p.deployment ?? p.bootstrap)?.mode}
          </Pill>
        </div>
      </PageHeader>

      {!p.measured && (
        <Notice tone="warn" title="Provisional values">
          The thresholds, runtimes and costs are planning values. A calibration
          on H100 workers replaces them with measured values in a new profile
          version.
        </Notice>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Card
          title="Current champion"
          subtitle="The complete stack that was actually tested."
        >
          <div className="grid grid-cols-2 gap-5">
            <Stat label="Version" value={`v${data.champion.version}`} />
            <Stat
              label="Capacity"
              value={rps(data.champion.capacity_milli_rps)}
              tone="accent"
              hint={
                data.champion.capacity_measured
                  ? "simulated, not an H100"
                  : "estimate, not yet measured"
              }
            />
            <Stat
              label="Gain"
              value={gain(data.champion.bound_gain_ppm)}
              hint="over the previous champion"
            />
            <Stat
              label="Promoted"
              value={
                data.champion.promoted_at
                  ? when(data.champion.promoted_at)
                  : "—"
              }
            />
          </div>
          <div className="mt-4">
            <KeyValue
              rows={[
                ["Author", data.champion.author ?? "none (tuned baseline)"],
                [
                  "Artifact",
                  data.champion.artifact_sha256 ? (
                    <Mono key="a">
                      {shortHash(data.champion.artifact_sha256)}
                    </Mono>
                  ) : (
                    "—"
                  ),
                ],
                ["Status", data.champion.status],
              ]}
            />
            {data.champion.attribution?.note && (
              <p className="mt-3 text-[12px] leading-relaxed text-muted">
                {data.champion.attribution.note}
              </p>
            )}
            {(data.champion.attribution?.components ?? []).length > 0 && (
              <div className="mt-3">
                <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">
                  Attribution
                </h3>
                <ul className="mt-1 space-y-1 text-[13px] text-muted">
                  {data.champion.attribution.components!.map((c) => (
                    <li key={c.hotkey}>
                      <span className="text-text">{c.lineage}</span> ·{" "}
                      {c.method}
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
            G = capacity(challenger) / fixed score(champion) − 1<br />G ≤ δ: the
            champion stays · G ≥ {gain(r.clear_win_ppm, 0)}: the challenger wins
            <br />
            in between: one more reading; the average of the two must exceed δ
            <br />
            and a winner must pass every quality gate and winner check
          </div>
          <div className="mt-4 grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Stat label="Margin δ" value={gain(r.delta_ppm, 0)} />
            <Stat
              label="Clear win"
              value={gain(r.clear_win_ppm, 0)}
              hint="no second reading"
            />
            <Stat label="Readings" value="1–2" hint="per evaluation" />
            <Stat
              label="Rate grid"
              value={`${gain(r.grid_step_ppm, 0)}`}
              hint="step between rates"
            />
          </div>
          <p className="mt-4 text-[13px] leading-relaxed text-muted">
            Ties keep the incumbent. The champion&apos;s score is measured once
            per worker, when it is crowned, and never again. If another
            submission is crowned while a measured winner waits, the winner is
            set against the new champion by arithmetic, (1 + G) / (1 + G
            <sub>new</sub>) − 1: nothing is measured again. A person reviews a winner only when an automatic check
            flags it.{" "}
            {r.calibrated
              ? ""
              : "The margin, clear-win line and rate grid are uncalibrated until a noise study is published."}
          </p>
        </Card>

        <Card
          title="Question bank"
          subtitle={`The owner's secret questions, a new bank every ${qb?.rule.period_days ?? 7} days. Validators use them; they do not write them.`}
        >
          {qb && qb.banks.length > 0 ? (
            <>
              <Table head={["Week", "Starts", "Status", "Fingerprint"]}>
                {qb.banks.slice(0, 4).map((b) => (
                  <tr key={b.bank_id}>
                    <Td className="num">{b.period_index}</Td>
                    <Td className="num whitespace-nowrap">
                      {when(b.starts_at).slice(0, 10)}
                    </Td>
                    <Td>
                      <Pill
                        tone={
                          b.status === "current"
                            ? "ok"
                            : b.status === "revealed"
                              ? "neutral"
                              : "info"
                        }
                      >
                        {b.status}
                      </Pill>
                    </Td>
                    <Td>
                      <Mono>{shortHash(b.commitment)}</Mono>
                    </Td>
                  </tr>
                ))}
              </Table>
              <p className="mt-3 text-[12px] leading-relaxed text-muted">
                Each bank holds{" "}
                {qb.rule.screening_long + qb.rule.screening_general} screening
                questions,{" "}
                {(
                  qb.rule.offline_long + qb.rule.offline_general
                ).toLocaleString("en-US")}{" "}
                quality questions and the traffic scripts for the capacity
                readings. Its fingerprint is published a day before its week
                starts; when the week ends the seed is published, so anyone can
                rebuild the bank and check the fingerprint. Every submission in
                a week answers the same questions, and each reading also mixes
                in a random beacon round nobody knows in advance.
              </p>
            </>
          ) : (
            <Empty title="No bank published yet">
              The first bank is committed when the controller starts.
            </Empty>
          )}
        </Card>

        <Card
          title="Fixed conditions"
          subtitle="Identical for the champion and every challenger."
        >
          <KeyValue
            rows={[
              ["Model", <Mono key="m">{p.model.repo}</Mono>],
              [
                "Model revision",
                <Mono key="mr">{shortHash(p.model.revision, 10)}</Mono>,
              ],
              [
                "Engine",
                <Mono key="e">{`${p.engine.repo} ${p.engine.tag}`}</Mono>,
              ],
              [
                "Engine commit",
                <Mono key="ec">{shortHash(p.engine.commit, 10)}</Mono>,
              ],
              [
                "Serving",
                `${p.model.mode ?? "non-thinking"} · ${p.model.decoding ?? "greedy"} decoding · up to ${(
                  p.model.max_model_len ?? 32768
                ).toLocaleString("en-US")} tokens`,
              ],
              [
                "Tuned baseline arguments",
                p.engine.args_sha256 ? (
                  <Mono key="ea">{shortHash(p.engine.args_sha256, 10)}</Mono>
                ) : (
                  "not pinned yet"
                ),
              ],
              ["GPU", p.hardware.gpu],
              [
                "Candidate VM",
                `${p.hardware.cpu_cores} cores · ${p.hardware.vm_ram_gib} GiB · no swap · no network`,
              ],
              [
                "GPU ceiling",
                `device memory − ${p.hardware.gpu_ceiling_margin_mib} MiB, sampled at the driver`,
              ],
              ["Isolation", p.hardware.isolation],
              ["Workloads", p.workloads.join(", ")],
              ["Model licence", p.model.license],
              [
                "Evaluator",
                p.evaluator
                  ? `version ${p.evaluator.version} · weights key ${p.evaluator.weights_version_key}`
                  : "—",
              ],
            ]}
          />
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">
                Allowed paths
              </h3>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-muted">
                {p.engine.allowed_paths.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">
                Forbidden paths
              </h3>
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
                <Term
                  term="TTFT"
                  plain="Time until the first answer token reaches the user"
                >
                  Time to first answer token
                </Term>
              </Td>
              <Td className="num">
                {p.latency.ttft_base_ms} ms + {p.latency.ttft_per_1k_prompt_ms}{" "}
                ms per 1k prompt tokens
              </Td>
              <Td>Users waiting before anything appears</Td>
            </tr>
            <tr>
              <Td>
                <Term
                  term="TPOT"
                  plain="Mean time between output tokens once the answer has started"
                >
                  Mean time per output token
                </Term>
              </Td>
              <Td className="num">{p.latency.tpot_mean_ms} ms</Td>
              <Td>Answers that crawl</Td>
            </tr>
            <tr>
              <Td>Attainment</Td>
              <Td className="num">
                {p.latency.attainment_bp / 100}% per run ·{" "}
                {p.latency.band_attainment_bp / 100}% per context band
              </Td>
              <Td>Long conversations pushed to the back</Td>
            </tr>
            <tr>
              <Td>Response-time drift and burst recovery</Td>
              <Td className="num">
                last quarter ≤ {p.latency.drift_q4_over_q2_bp / 10000}× the
                second · after a burst ≤{" "}
                {(p.latency.burst_recovery_bp ?? 0) / 10000}× the level before
                it
              </Td>
              <Td>A queue that never settles</Td>
            </tr>
            <tr>
              <Td>Errors, rejections, deadline misses</Td>
              <Td className="num">≤ {p.latency.max_error_bp / 100}%</Td>
              <Td>Dropping work to look fast</Td>
            </tr>
            <tr>
              <Td>Quality vs the champion</Td>
              <Td className="num">
                lower bound above −{p.quality.vs_champion_margin_bp / 100}{" "}
                points
              </Td>
              <Td>Trading accuracy for speed</Td>
            </tr>
            <tr>
              <Td>Accuracy under load</Td>
              <Td className="num">
                point estimate above −{p.quality.vs_champion_margin_bp / 100}{" "}
                points, lower bound above −
                {p.quality.vs_champion_stratum_margin_bp / 100}
              </Td>
              <Td>Answering worse once the GPU is busy</Td>
            </tr>
            <tr>
              <Td>Quality vs the frozen reference</Td>
              <Td className="num">
                lower bound above −{p.quality.vs_reference_margin_bp / 100}{" "}
                points
              </Td>
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
              <Td className="num">
                ≥ {p.quality.length_ratio_vs_reference_bp / 100}% of the
                reference
              </Td>
              <Td>Shorter answers that score well</Td>
            </tr>
          </Table>
          <p className="mt-3 text-[12px] leading-relaxed text-muted">
            Quality reference: <Mono>{p.quality.reference_id}</Mono>
          </p>
        </Card>

        <Card
          title="GPU time per submission"
          subtitle="Booked: screening and one evaluation, released as results come in. Winners' extra checks and a new champion's score come from the reserve."
        >
          <Table head={["Work", "GPU time", "Who uses it"]}>
            <tr>
              <Td>screening</Td>
              <Td className="num whitespace-nowrap">
                {centiHours(p.envelope.screen)}
              </Td>
              <Td>booked for every admission</Td>
            </tr>
            <tr>
              <Td>evaluation</Td>
              <Td className="num whitespace-nowrap">
                {centiHours(p.envelope.evaluation)}
              </Td>
              <Td>booked for every admission</Td>
            </tr>
            <tr>
              <Td className="font-semibold">booked per submission</Td>
              <Td className="num whitespace-nowrap font-semibold">
                {centiHours(p.envelope.screen + p.envelope.evaluation)}
              </Td>
              <Td>counts toward the two-week queue</Td>
            </tr>
            <tr>
              <Td>winner checks</Td>
              <Td className="num whitespace-nowrap">
                {centiHours(p.envelope.winner_checks)}
              </Td>
              <Td>winners only, from the reserve</Td>
            </tr>
            <tr>
              <Td>new champion&apos;s score</Td>
              <Td className="num whitespace-nowrap">
                {centiHours(p.envelope.recalibration_on_promotion)}
              </Td>
              <Td>once per promotion, on every worker, from the reserve</Td>
            </tr>
            <tr>
              <Td>champion&apos;s answers to a new bank</Td>
              <Td className="num whitespace-nowrap">
                {centiHours(p.envelope.champion_answers_per_bank)}
              </Td>
              <Td>once per worker per week, from the reserve</Td>
            </tr>
          </Table>
          <p className="mt-3 text-[12px] leading-relaxed text-muted">
            Submitting is free: the owner runs the evaluation workers and bears
            the GPU time. Joining the queue needs a hotkey registered on the
            subnet, and each hotkey and lineage has one active submission at a
            time.
          </p>
        </Card>

        <Card
          title="Weight result"
          subtitle="Deterministic from the king queue: each king below King #1 earns 20% of the miner allocation and King #1 earns the rest, including the share of every empty slot. With no king, and for an ineligible king, the share goes to the owner UID to be burned."
        >
          {data.weight_plan ? (
            <>
              <p className="text-[14px] leading-relaxed text-muted">
                Every tempo the owner signs the weights by hotkey and serves
                them only to validators, who read them with a request signed by
                their validator hotkey and set their weights from them. The
                weights are not published on this site.
              </p>
              <div className="mt-3 space-y-2">
                <Pill tone="sim">
                  status: {data.weight_plan.status.replace(/_/g, " ")}
                </Pill>{" "}
                <Pill tone={data.weight_plan.writer_enabled ? "ok" : "warn"}>
                  writer{" "}
                  {data.weight_plan.writer_enabled ? "enabled" : "disabled"}
                </Pill>
                {data.weight_plan.notes.map((n) => (
                  <p key={n} className="text-[12px] leading-relaxed text-muted">
                    {n}
                  </p>
                ))}
                <p className="text-[12px] leading-relaxed text-muted">
                  Chain consensus and realized emissions can differ from a
                  recommended vector. The champion never receives the owner or
                  validator shares.
                </p>
              </div>
            </>
          ) : (
            <Empty title="No weight plan yet">
              A plan is produced after the first promotion.
            </Empty>
          )}
        </Card>
      </div>
    </div>
  );
}
