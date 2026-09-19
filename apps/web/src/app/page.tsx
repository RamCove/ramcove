import { AutoRefresh, TimeAgo } from "@/components/client";
import { CoveContours } from "@/components/cove-contours";
import { Empty, KeyValue, Mono, Notice, Pill, SimulatedTag, Table, Td, Term } from "@/components/ui";
import { isPreview } from "@/lib/preview";
import { apiGetOrNull, snapshotTakenAt } from "@/lib/server-api";
import { centiHours, gain, rps, usd } from "@/lib/format";
import { WHITEPAPER_PDF } from "@/lib/site";
import clsx from "clsx";
import Link from "next/link";
import type React from "react";
import type { ReactNode } from "react";

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

type Profile = { profile: { replacement: { delta_ppm: number; blocks: number } } };

const CONTAINER = "mx-auto w-full max-w-[1200px] px-5 sm:px-8";

export default async function HomePage() {
  const [data, profile] = await Promise.all([
    apiGetOrNull<Overview>("/v1/overview"),
    apiGetOrNull<Profile>("/v1/profile"),
  ]);
  if (!data) {
    return <Empty title="No data yet">Start the API and the controller, then reload this page.</Empty>;
  }
  const margin = profile ? `${profile.profile.replacement.delta_ppm / 10_000}%` : "5%";
  const blocks = profile?.profile.replacement.blocks ?? 5;

  return (
    <div className="full-bleed">
      <Hero data={data} margin={margin} blocks={blocks} />

      {data.incidents.length > 0 && (
        <div className={clsx(CONTAINER, "space-y-3 pt-10")}>
          {data.incidents.map((i) => (
            <Notice key={i.id} tone={i.severity === "info" ? "info" : "warn"} title={i.title}>
              {i.summary}
            </Notice>
          ))}
        </div>
      )}

      <Idea />
      <HowItWorks margin={margin} blocks={blocks} />
      <Principles margin={margin} blocks={blocks} />
      <LiveBoard data={data} />
      <Audiences />
      <WhatIsReal />
      <Closing />
    </div>
  );
}

/* ───────────────────────────── Hero ───────────────────────────── */

function Hero({ data, margin, blocks }: { data: Overview; margin: string; blocks: number }) {
  return (
    <section className="relative overflow-hidden border-b border-line">
      <CoveContours className="contour-fade pointer-events-none absolute inset-0 h-full w-full" />
      <div aria-hidden className="glow glow-drift pointer-events-none absolute -right-40 -top-40 h-[720px] w-[720px]" />
      <div className={clsx(CONTAINER, "relative pb-16 pt-14 sm:pt-20 lg:pb-20 lg:pt-24")}>
        <div className="grid items-center gap-14 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
          <div className="min-w-0">
            <p className="eyebrow rise">Proposed Bittensor subnet · Qwen3.8-27B on one H100</p>
            <h1 className="font-display text-balance rise rise-1 mt-6 text-[60px] leading-[0.95] text-text sm:text-[84px] lg:text-[96px]">
              More AI.
              <br />
              <span className="display-accent accent-shine">Same GPU.</span>
            </h1>
            <p className="rise rise-2 mt-8 max-w-xl text-[18px] leading-[1.6] text-muted sm:text-[19px]">
              RamCove pays for software changes that let one fixed GPU serve more useful AI requests. Every
              challenger is measured against the reigning champion, checked by people, and paid only when the
              gain is real.
            </p>
            <div className="rise rise-3 mt-9 flex flex-wrap items-center gap-3">
              <Link
                href="/docs#miners"
                className="inline-flex h-12 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-6 text-[15px] font-medium text-on-accent shadow-[inset_0_1px_0_rgb(255_255_255/0.18),0_10px_28px_-12px_var(--accent)] transition-colors hover:bg-accent-strong"
              >
                Start mining <span aria-hidden>→</span>
              </Link>
              <Link
                href="/docs/rules"
                className="inline-flex h-12 items-center rounded-[var(--radius-sm)] border border-line-strong bg-surface/70 px-6 text-[15px] font-medium text-text backdrop-blur transition-colors hover:bg-surface"
              >
                Read the rules
              </Link>
            </div>
            <p className="rise rise-4 mt-6 text-[14px] text-muted">
              Running a validator?{" "}
              <Link href="/docs#validators" className="link">
                Read the validator guide
              </Link>
            </p>
          </div>
          <div className="rise rise-2 min-w-0">
            <ChampionPanel data={data} />
          </div>
        </div>

        <dl className="mt-16 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-card)] border border-line bg-line lg:mt-20 lg:grid-cols-4">
          <HeroStat value={margin} label="margin a challenger must clear" />
          <HeroStat value={String(blocks)} label="paired blocks decide each promotion" />
          <HeroStat
            value={centiHours(data.capacity.envelope_per_admission_centi)}
            label="reserved per paid admission"
          />
          <HeroStat value="1" label="champion holds the miner allocation" />
        </dl>
      </div>
    </section>
  );
}

function HeroStat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex flex-col bg-bg px-5 py-6 sm:px-7">
      <dt className="order-2 mt-1.5 text-[13px] leading-snug text-muted">{label}</dt>
      <dd className="num order-1 font-mono text-[20px] font-medium tracking-[-0.02em] text-text sm:text-[30px]">
        {value}
      </dd>
    </div>
  );
}

function ChampionPanel({ data }: { data: Overview }) {
  const { champion, queue, capacity } = data;
  const history = [...data.champion_history].sort((a, b) => a.version - b.version).slice(-4);
  const peak = Math.max(1, ...history.map((h) => h.capacity_milli_rps ?? 0));
  return (
    <div
      className="overflow-hidden rounded-[20px] border border-line bg-surface/90 backdrop-blur"
      style={{ boxShadow: "var(--shadow-lift)" }}
    >
      <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
        <div className="min-w-0">
          <p className="eyebrow">Reigning champion</p>
          <p className="mt-1.5 text-[18px] font-semibold tracking-[-0.01em] text-text">
            Version {champion.version}
            <span className="ml-2 font-normal text-muted">{champion.is_baseline ? "baseline" : "challenger"}</span>
          </p>
          <p className="mt-1 truncate font-mono text-[11.5px] text-faint" title={`${data.profile.id}@${data.profile.version}`}>
            {data.profile.title}
          </p>
        </div>
        <SimulatedTag what={champion.capacity_measured ? "measured" : "simulated"} />
      </div>

      <div className="px-6 py-6">
        <p className="eyebrow">
          Qualified serving capacity{" "}
          <span className="normal-case tracking-normal text-faint">(P-mem)</span>
        </p>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="num font-mono text-[44px] font-medium leading-none tracking-[-0.03em] text-text">
            {rps(champion.capacity_milli_rps).replace(" req/s", "")}
          </span>
          <span className="font-mono text-[14px] text-muted">req/s</span>
          <span
            className={clsx(
              "num ml-auto font-mono text-[14px]",
              champion.bound_gain_ppm ? "text-ok" : "text-faint",
            )}
          >
            {champion.bound_gain_ppm ? `${gain(champion.bound_gain_ppm)} confirmed` : "baseline"}
          </span>
        </div>
        <p className="mt-3 text-[14px] leading-relaxed text-muted">
          {champion.is_baseline ? (
            <>No miner holds the crown yet. Version 0 is the tuned baseline and earns nothing.</>
          ) : (
            <>
              Held by <span className="font-mono text-text">{champion.author}</span>, who receives the miner
              allocation until someone proves better.
            </>
          )}
        </p>

        <ul className="mt-6 space-y-3" aria-label="Approved capacity by version">
          {history.map((h) => {
            const pct = Math.max(4, Math.round(((h.capacity_milli_rps ?? 0) / peak) * 100));
            const current = h.status === "current";
            return (
              <li key={h.version}>
                <div className="flex items-baseline justify-between gap-3 text-[13px]">
                  <span className="text-text">
                    v{h.version}
                    <span className="ml-2 font-mono text-[12px] text-faint">{h.author ?? "baseline"}</span>
                  </span>
                  <span className="num font-mono text-[12.5px] text-muted">{rps(h.capacity_milli_rps)}</span>
                </div>
                <div className="mt-1.5 h-[5px] rounded-full bg-surface-3">
                  <div
                    className={clsx("bar-grow h-full rounded-full", current ? "bg-accent" : "bg-line-strong")}
                    style={{ width: `${pct}%`, animationDelay: `${300 + h.version * 180}ms` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      <dl className="grid grid-cols-3 border-t border-line">
        <PanelCell label="In evaluation" value={queue.admitted_active} />
        <PanelCell label="Waiting, free" value={queue.waiting_list} />
        <PanelCell label="Workers ready" value={`${capacity.workers_ready}/${capacity.workers_total}`} />
      </dl>
      <div className="flex items-center justify-between gap-3 border-t border-line bg-surface-2/60 px-6 py-3">
        <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
          {isPreview() ? (
            <>
              <span aria-hidden className="inline-block h-[7px] w-[7px] rounded-full bg-sim" />
              Snapshot · {(snapshotTakenAt() ?? "").slice(0, 10) || "undated"}
            </>
          ) : (
            <>
              <span aria-hidden className="live-dot text-ok" />
              Live from this build
            </>
          )}
        </span>
        <span className="font-mono text-[11px] text-faint">
          {data.chain ? <>dev chain · block {data.chain.finalized_number}</> : <>rules {data.profile.rule_hash.slice(0, 8)}</>}
        </span>
      </div>
    </div>
  );
}

function PanelCell({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="border-line px-6 py-4 [&:not(:last-child)]:border-r">
      <dt className="eyebrow text-[10px]">{label}</dt>
      <dd className="num mt-1 font-mono text-[18px] text-text">{value}</dd>
    </div>
  );
}

/* ───────────────────────────── Sections ───────────────────────────── */

function Section({
  index,
  label,
  title,
  children,
  band,
  id,
  aside,
}: {
  index: string;
  label: string;
  title: ReactNode;
  children?: ReactNode;
  band?: boolean;
  id?: string;
  aside?: ReactNode;
}) {
  return (
    <section id={id} className={clsx("border-b border-line", band && "bg-surface")}>
      <div className={clsx(CONTAINER, "py-20 sm:py-28")}>
        <div className="reveal flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-3xl">
            <p className="eyebrow">
              <span className="text-accent-ink">{index}</span> · {label}
            </p>
            <h2 className="font-display text-balance mt-5 text-[38px] leading-[1.05] text-text sm:text-[54px]">{title}</h2>
          </div>
          {aside}
        </div>
        {children && <div className="reveal mt-14">{children}</div>}
      </div>
    </section>
  );
}

function Idea() {
  return (
    <section className="border-b border-line">
      <div className={clsx(CONTAINER, "grid gap-10 py-20 sm:py-28 lg:grid-cols-[220px_1fr]")}>
        <p className="eyebrow pt-3">
          <span className="text-accent-ink">01</span> · The idea
        </p>
        <div className="reveal max-w-3xl">
          <h2 className="font-display text-balance text-[38px] leading-[1.08] text-text sm:text-[54px]">
            Every GPU that is already paid for has <span className="display-accent">more to give.</span>
          </h2>
          <div className="mt-8 space-y-5 text-[17px] leading-[1.7] text-muted">
            <p>
              Serving a large model is mostly a memory problem. How many conversations a GPU can hold at once,
              how much of each it must recompute, how little it wastes between requests: small changes in the
              serving stack decide how much useful work the same hardware does.
            </p>
            <p>
              RamCove turns finding those changes into an open competition. Anyone can submit a patch to a pinned
              inference engine. Validators build it in isolation, measure how many{" "}
              <Term
                term="qualified requests"
                plain="Requests answered correctly, fast enough and without errors, at a steady rate"
              />{" "}
              per second it sustains, and compare it with the champion under identical conditions.
            </p>
          </div>
          <blockquote className="mt-10 border-l-2 border-accent pl-6">
            <p className="font-display text-balance text-[22px] italic leading-[1.4] text-text sm:text-[26px]">
              Not one faster server, but a market where anyone can prove their change makes the same hardware
              serve more — and is paid only when it does.
            </p>
          </blockquote>
        </div>
      </div>
    </section>
  );
}

function HowItWorks({ margin, blocks }: { margin: string; blocks: number }) {
  const steps: [string, string, string, string][] = [
    ["01", "Free checks", "Format, signature, allowed paths, licences and duplicates are checked before anyone pays.", "Free"],
    ["02", "Reserve and pay", "When evaluation capacity exists you get a time-limited quote and pay a fee in TAO. Otherwise you wait for free.", "Fee in TAO"],
    ["03", "Measured", `Screening, a full evaluation, then ${blocks} paired blocks against the frozen champion on identical hardware.`, "Paired blocks"],
    ["04", "Reviewed", "People check the code, licence and safety against published criteria before any crown changes hands.", "Human review"],
    ["05", "Crowned", `If the lower bound clears the ${margin} margin, the challenger becomes champion and the weights follow.`, "Winner takes all"],
  ];
  return (
    <Section
      index="02"
      label="How it works"
      title={
        <>
          From patch to <span className="display-accent">crown</span> in five steps.
        </>
      }
      band
    >
      <ol className="grid gap-px overflow-hidden rounded-[var(--radius-card)] border border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
        {steps.map(([n, title, body, tag]) => (
          <li
            key={n}
            className="reveal flex flex-col bg-bg p-6 transition-colors hover:bg-surface"
            style={{ "--i": Number(n) - 1 } as React.CSSProperties}
          >
            <span className="font-mono text-[13px] text-accent-ink">{n}</span>
            <p className="mt-10 text-[18px] font-semibold tracking-[-0.01em] text-text">{title}</p>
            <p className="mt-2 flex-1 text-[14px] leading-relaxed text-muted">{body}</p>
            <span className="eyebrow mt-6 border-t border-line pt-4">{tag}</span>
          </li>
        ))}
      </ol>
    </Section>
  );
}

function Principles({ margin, blocks }: { margin: string; blocks: number }) {
  const items: { title: string; body: string; detail: string }[] = [
    {
      title: "Order comes from the chain",
      body: "Paid admissions are ordered by their finalized payment. A later submission cannot promote while any earlier paid one is still being evaluated, so finishing fast never jumps the queue.",
      detail: "key = (finalized block, extrinsic index)",
    },
    {
      title: "Paid only when the gain is real",
      body: `A challenger must clear a ${margin} margin on the lower bound of a one-sided 95% interval across ${blocks} paired blocks — not on its best run.`,
      detail: `exp(L) − 1 > ${margin}`,
    },
    {
      title: "One champion, one allocation",
      body: "The champion takes the whole miner allocation until someone proves better. There is no daily winner and no dilution; with no miner champion, the allocation is burned.",
      detail: "winner takes all",
    },
    {
      title: "Everything is on the record",
      body: "Decisions land in an append-only, hash-chained audit log. No route lets the operator edit a score or crown a champion by hand.",
      detail: "sha-256 chain · verifiable",
    },
  ];
  return (
    <Section
      index="03"
      label="Fair by construction"
      title={
        <>
          Rules you can check, <span className="display-accent">not promises.</span>
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-2">
        {items.map((it, i) => (
          <article
            key={it.title}
            className="reveal group relative overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface p-8 transition-[box-shadow,transform] duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lift)]"
            style={{ "--i": i } as React.CSSProperties}
          >
            <span className="font-mono text-[12px] text-faint">0{i + 1}</span>
            <h3 className="font-display text-balance mt-6 text-[28px] leading-[1.15] text-text">{it.title}</h3>
            <p className="mt-3 max-w-lg text-[15px] leading-relaxed text-muted">{it.body}</p>
            <p className="mt-8 inline-flex rounded-full border border-line bg-bg px-3 py-1.5 font-mono text-[12px] text-text">
              {it.detail}
            </p>
          </article>
        ))}
      </div>
    </Section>
  );
}

function LiveBoard({ data }: { data: Overview }) {
  const { capacity, queue, chain } = data;
  const used = capacity.capacity_centi_gpu_hours
    ? Math.min(100, Math.round((capacity.committed_centi_gpu_hours / capacity.capacity_centi_gpu_hours) * 100))
    : 0;
  return (
    <Section
      index="04"
      label={isPreview() ? "Recorded from this build" : "Live from this build"}
      title={
        isPreview() ? (
          <>
            The competition, <span className="display-accent">as recorded.</span>
          </>
        ) : (
          <>
            The competition, <span className="display-accent">right now.</span>
          </>
        )
      }
      band
      aside={<AutoRefresh />}
    >
      <div className="grid items-start gap-5 lg:grid-cols-[1.5fr_1fr]">
        <div className="min-w-0 space-y-8">
          <div
            className="min-w-0 rounded-[var(--radius-card)] border border-line bg-bg"
            style={{ boxShadow: "var(--shadow)" }}
          >
            <div className="flex flex-wrap items-center justify-between gap-3 px-6 pb-2 pt-5">
              <div>
                <p className="eyebrow">Approved capacity history</p>
                <p className="mt-1.5 text-[16px] font-semibold text-text">Every champion, in order</p>
              </div>
              <Link href="/docs/rules" className="link text-[14px]">
                Full rules →
              </Link>
            </div>
            <div className="px-6 pb-4 pt-3">
              <Table
                head={["Version", "Author", "Capacity", "Confirmed gain", "Status"]}
                empty={data.champion_history.length === 0}
                minWidth={520}
              >
                {data.champion_history.map((c) => (
                  <tr key={c.version}>
                    <Td className="font-medium">v{c.version}</Td>
                    <Td>
                      {c.author ? <Mono>{c.author}</Mono> : <span className="text-faint">baseline</span>}
                    </Td>
                    <Td className="num font-mono text-[13px]">{rps(c.capacity_milli_rps)}</Td>
                    <Td className="num font-mono text-[13px]">{gain(c.bound_gain_ppm)}</Td>
                    <Td>
                      <Pill
                        dot
                        tone={c.status === "current" ? "ok" : c.status === "rolled_back" ? "danger" : "neutral"}
                      >
                        {c.status}
                      </Pill>
                    </Td>
                  </tr>
                ))}
              </Table>
            </div>
          </div>
          <div
            className="rounded-[var(--radius-card)] border border-line bg-bg p-6"
            style={{ boxShadow: "var(--shadow)" }}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <div>
                <p className="eyebrow">Chain and evidence</p>
                <p className="mt-1.5 text-[16px] font-semibold text-text">
                  What this build reads, and what it only proposes
                </p>
              </div>
              {chain?.simulated && <SimulatedTag what="dev chain" />}
            </div>
            <div className="mt-5">
              <KeyValue
                rows={[
                  ["Finalized block", chain ? <span className="font-mono">{chain.finalized_number}</span> : "—"],
                  ["Observed", chain ? <TimeAgo key="o" at={chain.observed_at} /> : "—"],
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
            </div>
            <p className="mt-6 text-[13px] leading-relaxed text-muted">
              Weight plans are proposed only. Nothing is submitted to a chain in this build, and the champion never
              receives owner or validator emissions.
            </p>
          </div>
        </div>

        <div
          className="min-w-0 rounded-[var(--radius-card)] border border-line bg-bg p-6"
          style={{ boxShadow: "var(--shadow)" }}
        >
          <p className="eyebrow">Evaluation capacity</p>
          <p className="mt-1.5 text-[16px] font-semibold text-text">Capped by a reservation, not an average</p>
          <div className="mt-6">
            <div className="flex items-baseline justify-between">
              <span className="num font-mono text-[28px] tracking-[-0.02em] text-text">
                {centiHours(capacity.committed_centi_gpu_hours)}
              </span>
              <span className="num font-mono text-[13px] text-muted">
                of {centiHours(capacity.capacity_centi_gpu_hours)}
              </span>
            </div>
            <div className="mt-3 h-2 rounded-full bg-surface-3" role="img" aria-label={`${used}% of capacity reserved`}>
              <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(used, 2)}%` }} />
            </div>
            <p className="mt-2 text-[13px] text-muted">
              reserved over the next {capacity.horizon_hours} hours · {used}% committed
            </p>
          </div>
          <dl className="mt-6 grid grid-cols-3 gap-4 border-t border-line pt-5">
            <MiniStat label="Workers" value={`${capacity.workers_ready}/${capacity.workers_total}`} />
            <MiniStat label="Active" value={queue.admitted_active} />
            <MiniStat label="Waiting" value={queue.waiting_list} />
          </dl>
          <div className="mt-6">
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
        </div>
      </div>

    </Section>
  );
}

function MiniStat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="eyebrow text-[10px]">{label}</dt>
      <dd className="num mt-1 font-mono text-[18px] text-text">{value}</dd>
    </div>
  );
}

function Audiences() {
  const cards = [
    {
      who: "For miners",
      title: "Make the GPU do more. Get paid for it.",
      points: [
        "Submit a patch to the pinned engine with the ramcove-miner command line",
        "See the fee, the refund rules and the queue position before you pay",
        "Follow every stage on the dashboard, and read exactly why a submission ended",
      ],
      href: "/docs#miners",
      cta: "Read the miner guide",
    },
    {
      who: "For validators",
      title: "Measure fairly. Sign what you saw.",
      points: [
        "Run evaluations on isolated workers that fail closed when unsafe",
        "Paired blocks against a frozen champion keep comparisons honest",
        "Every report is signed and lands in the audit chain",
      ],
      href: "/docs#validators",
      cta: "Read the validator guide",
    },
  ];
  return (
    <Section
      index="05"
      label="Who it is for"
      title={
        <>
          Two roles, <span className="display-accent">one scoreboard.</span>
        </>
      }
    >
      <div className="grid gap-5 lg:grid-cols-2">
        {cards.map((c, i) => (
          <article
            key={c.who}
            style={{ "--i": i } as React.CSSProperties}
            className={clsx(
              "reveal flex flex-col rounded-[var(--radius-card)] border p-8 transition-transform duration-300 hover:-translate-y-1 sm:p-10",
              i === 0 ? "border-transparent bg-band text-on-band" : "border-line bg-surface text-text",
            )}
          >
            <p className={clsx("eyebrow", i === 0 && "!text-on-band/70")}>{c.who}</p>
            <h3 className="font-display text-balance mt-6 text-[32px] leading-[1.1] sm:text-[38px]">{c.title}</h3>
            <ul className="mt-8 flex-1 space-y-3.5">
              {c.points.map((p) => (
                <li key={p} className="flex gap-3 text-[15px] leading-relaxed">
                  <span aria-hidden className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  <span className={i === 0 ? "text-on-band/80" : "text-muted"}>{p}</span>
                </li>
              ))}
            </ul>
            <Link
              href={c.href}
              className={clsx(
                "mt-10 inline-flex h-11 w-fit items-center gap-2 rounded-[var(--radius-sm)] px-5 text-[14px] font-medium transition-colors",
                i === 0
                  ? "bg-accent text-on-accent hover:bg-accent-strong"
                  : "border border-line-strong bg-bg text-text hover:bg-surface-2",
              )}
            >
              {c.cta} <span aria-hidden>→</span>
            </Link>
          </article>
        ))}
      </div>
    </Section>
  );
}

function WhatIsReal() {
  const working = [
    "Competition rules, queue order and promotion barrier",
    "Payment verification, receipts, refunds and the audit chain",
    "Race-safe accounting on a real PostgreSQL database",
    "Read-only parsing of live Bittensor blocks",
  ];
  const notYet = [
    "GPU measurement is a labelled simulation — no H100 yet",
    "The chain, beacon and payments are a local dev chain",
    "No real isolation backend; workers accept trusted fixtures only",
    "Thresholds are provisional until a real noise study",
  ];
  return (
    <Section
      index="06"
      label="Honest status"
      title={
        <>
          What is real today, <span className="display-accent">and what is not.</span>
        </>
      }
      band
      aside={
        <Link href="/status" className="link text-[15px]">
          Service status →
        </Link>
      }
    >
      <div className="grid gap-5 md:grid-cols-2">
        <StatusList title="Working in this build" tone="ok" items={working} />
        <StatusList title="Simulated or still ahead" tone="sim" items={notYet} />
      </div>
    </Section>
  );
}

function StatusList({ title, tone, items }: { title: string; tone: "ok" | "sim"; items: string[] }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-bg p-8">
      <Pill tone={tone} dot>
        {title}
      </Pill>
      <ul className="mt-6 divide-y divide-line">
        {items.map((t) => (
          <li key={t} className="flex gap-3 py-3.5 text-[15px] leading-relaxed text-text">
            <span aria-hidden className={clsx("font-mono text-[13px]", tone === "ok" ? "text-ok" : "text-sim")}>
              {tone === "ok" ? "✓" : "○"}
            </span>
            {t}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Closing() {
  return (
    <section className="relative overflow-hidden bg-band text-on-band">
      <div aria-hidden className="glow pointer-events-none absolute -bottom-60 left-1/2 h-[640px] w-[900px] -translate-x-1/2" />
      <div className={clsx(CONTAINER, "reveal relative py-24 text-center sm:py-32")}>
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-on-band/60">Get started</p>
        <h2 className="font-display text-balance mx-auto mt-6 max-w-3xl text-[44px] leading-[1.02] sm:text-[72px]">
          Help one GPU <span className="display-accent">serve more.</span>
        </h2>
        <p className="mx-auto mt-6 max-w-xl text-[17px] leading-relaxed text-on-band/70">
          The free checks cost nothing. Pack a patch, see what the validators will see, and decide whether to
          compete.
        </p>
        <div className="mt-10 flex flex-wrap justify-center gap-3">
          <Link
            href="/docs#miners"
            className="inline-flex h-12 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-6 text-[15px] font-medium text-on-accent transition-colors hover:bg-accent-strong"
          >
            Start mining <span aria-hidden>→</span>
          </Link>
          <a
            href={WHITEPAPER_PDF}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-12 items-center gap-2 rounded-[var(--radius-sm)] border border-on-band/25 px-6 text-[15px] font-medium text-on-band transition-colors hover:bg-on-band/10"
          >
            Read the whitepaper <span aria-hidden>↗</span>
          </a>
        </div>
      </div>
    </section>
  );
}
