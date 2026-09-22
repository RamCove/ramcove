import { AutoRefresh, TimeAgo } from "@/components/client";
import {
  Card,
  Empty,
  PageHeader,
  Pill,
  Stat,
  Table,
  Td,
} from "@/components/ui";
import { apiGetOrNull } from "@/lib/server-api";
import { rps, when } from "@/lib/format";
import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Status" };

type Status = {
  profile: string;
  workers: {
    id: string;
    online: boolean;
    safe_and_ready: boolean;
    provider: string;
    untrusted_code_isolation: boolean;
  }[];
  fixed_scores?: {
    worker: string;
    champion_version: number | null;
    current: boolean;
    fixed_score_milli_rps: number | null;
    tight_fixed_score_milli_rps: number | null;
    measured_at: string | null;
  }[];
  expired_leases_waiting_for_sweep: number;
  chain: {
    finalized_number: number;
    simulated: boolean;
    observed_at: string;
  } | null;
  incidents: {
    id: string;
    severity: string;
    title: string;
    summary: string;
    started_at: string;
    resolved_at: string | null;
  }[];
  meta: {
    env: string;
    network: string;
    simulated_chain: boolean;
    chain_writes_enabled: boolean;
    notice: string;
  };
};

export default async function StatusPage() {
  const s = await apiGetOrNull<Status>("/v1/status");
  if (!s) {
    return (
      <Card title="Service status">
        <Empty title="The API is not reachable">
          Start it with <code className="font-mono">make api</code>. Until then
          this page cannot report anything.
        </Empty>
      </Card>
    );
  }
  const ready = s.workers.filter((w) => w.safe_and_ready).length;
  const open = s.incidents.filter((i) => !i.resolved_at);
  return (
    <div className="min-w-0 space-y-8">
      <PageHeader
        eyebrow="System"
        title="Service status"
        lede={s.meta.notice}
        actions={<AutoRefresh seconds={8} />}
      />

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <Stat
            label="Evaluation"
            value={ready > 0 ? "available" : "unavailable"}
            tone={ready > 0 ? "ok" : "warn"}
            hint={`${ready} of ${s.workers.length} workers safe and ready`}
          />
        </Card>
        <Card>
          <Stat
            label="Chain reads"
            value={s.chain ? "observed" : "stale"}
            tone={s.chain ? "ok" : "warn"}
            hint={
              s.chain ? (
                <>
                  {`#${s.chain.finalized_number} · `}
                  <TimeAgo at={s.chain.observed_at} />
                </>
              ) : (
                "no observation"
              )
            }
          />
        </Card>
        <Card>
          <Stat
            label="Chain writes"
            value={s.meta.chain_writes_enabled ? "enabled" : "disabled"}
            tone={s.meta.chain_writes_enabled ? "warn" : "default"}
            hint="weight plans are proposed only"
          />
        </Card>
        <Card>
          <Stat
            label="Open incidents"
            value={open.length}
            tone={open.length > 0 ? "warn" : "ok"}
            hint={`${s.incidents.length} recorded`}
          />
        </Card>
      </div>

      <Card title="Workers">
        <Table
          head={[
            "Worker",
            "Online",
            "Safe and ready",
            "Provider",
            "Untrusted code",
          ]}
        >
          {s.workers.map((w) => (
            <tr key={w.id}>
              <Td>{w.id}</Td>
              <Td>
                {w.online ? (
                  <Pill tone="ok">online</Pill>
                ) : (
                  <Pill tone="warn">offline</Pill>
                )}
              </Td>
              <Td>
                {w.safe_and_ready ? (
                  <Pill tone="ok">ready</Pill>
                ) : (
                  <Pill tone="danger">not ready</Pill>
                )}
              </Td>
              <Td>{w.provider}</Td>
              <Td>
                {w.untrusted_code_isolation ? (
                  <Pill tone="ok">isolated</Pill>
                ) : (
                  <Pill tone="warn">trusted fixtures only</Pill>
                )}
              </Td>
            </tr>
          ))}
        </Table>
      </Card>

      <Card
        title="The champion's fixed score, per worker"
        subtitle="Each worker measures the champion once, when it is crowned, and every challenger on that worker is compared with that worker's number. Physical GPUs differ, so the numbers differ."
      >
        {!s.fixed_scores || s.fixed_scores.length === 0 ? (
          <Empty title="No worker has measured the champion yet" />
        ) : (
          <Table
            head={[
              "Worker",
              "Champion",
              "Fixed score",
              "At the tighter budget",
              "Measured",
            ]}
          >
            {s.fixed_scores.map((f) => (
              <tr key={f.worker}>
                <Td>{f.worker}</Td>
                <Td>
                  v{f.champion_version}{" "}
                  {f.current ? (
                    <Pill tone="ok">current</Pill>
                  ) : (
                    <Pill tone="warn">out of date</Pill>
                  )}
                </Td>
                <Td className="num font-mono text-[13px]">
                  {rps(f.fixed_score_milli_rps)}
                </Td>
                <Td className="num font-mono text-[13px]">
                  {rps(f.tight_fixed_score_milli_rps)}
                </Td>
                <Td className="text-[13px] text-muted">
                  {f.measured_at ? <TimeAgo at={f.measured_at} /> : "—"}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card
        title="Incidents"
        subtitle="Paused intake and infrastructure problems are reported here, not hidden."
      >
        {s.incidents.length === 0 ? (
          <Empty title="No incidents recorded" />
        ) : (
          <ul className="space-y-2">
            {s.incidents.map((i) => (
              <li
                key={i.id}
                className="rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Pill
                    tone={
                      i.resolved_at
                        ? "ok"
                        : i.severity === "info"
                          ? "info"
                          : "warn"
                    }
                  >
                    {i.resolved_at ? "resolved" : i.severity}
                  </Pill>
                  <span className="text-[13px] font-medium text-text">
                    {i.title}
                  </span>
                  <span className="text-[11px] text-faint">
                    started {<TimeAgo at={i.started_at} />}
                  </span>
                </div>
                <p className="mt-1 text-[12px] leading-relaxed text-muted">
                  {i.summary}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <p className="text-[13px] text-muted">
        A submission that failed links to the matching section in the{" "}
        <Link href="/docs" className="text-accent hover:underline">
          documentation
        </Link>
        .
      </p>
    </div>
  );
}
