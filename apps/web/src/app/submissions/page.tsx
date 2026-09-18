import { PreviewGate } from "@/components/preview-gate";
import { isPreview } from "@/lib/preview";
import { TimeAgo } from "@/components/client";
import { Card, Empty, Notice, PageHeader, Pill, StatePill, Table, Td } from "@/components/ui";
import { apiGetOrNull } from "@/lib/server-api";
import { gain, when } from "@/lib/format";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "My submissions" };

type Mine = {
  items: {
    submission_id: string;
    state: string;
    state_label: string;
    lineage: string;
    created_at: string;
    updated_at: string;
    admission_key: [number, number] | null;
    outcome: { code: string | null; summary: string | null; fee: string | null };
    support_ref: string;
    triage_gain_ppm: number | null;
    bound_gain_ppm: number | null;
  }[];
  credits: { id: string; amount_rao: number; amount_tao: string; reason: string; expires_at: string }[];
};

export default async function MySubmissionsPage() {
  if (isPreview()) {
    return (
      <div className="min-w-0 space-y-8">
        <PreviewGate what="Your submissions list" />
      </div>
    );
  }
  const cookie = (await cookies()).toString();
  const data = await apiGetOrNull<Mine>("/v1/miner/submissions", cookie);
  if (!data) {
    return (
      <Card title="My submissions">
        <Empty title="Sign in to see your submissions">
          Use the sign-in button at the top right. Your hotkey signs a message that authorizes no payment.
        </Empty>
      </Card>
    );
  }
  return (
    <div className="min-w-0 space-y-8">
      <PageHeader
        eyebrow="For miners"
        title="My submissions"
        lede="Every submission you have started, with its outcome and its fee."
        actions={
          <Link
            href="/submit"
            className="inline-flex h-10 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-4 text-[14px] font-medium text-on-accent transition-colors hover:bg-accent-strong"
          >
            New submission <span aria-hidden>→</span>
          </Link>
        }
      />

      {data.credits.length > 0 && (
        <Notice tone="ok" title="You have unused credits">
          <ul className="mt-1 space-y-1">
            {data.credits.map((c) => (
              <li key={c.id}>
                {c.amount_tao} TAO — {c.reason} (expires {when(c.expires_at)})
              </li>
            ))}
          </ul>
        </Notice>
      )}

      <Card title="Submissions">
        {data.items.length === 0 ? (
          <Empty title="Nothing submitted yet">
            Start with the free checks; you are only asked to pay once capacity is reserved for you.
          </Empty>
        ) : (
          <Table head={["Submission", "State", "Result", "Fee", "Support ref", "Updated"]}>
            {data.items.map((s) => (
              <tr key={s.submission_id}>
                <Td>
                  <Link href={`/submissions/${s.submission_id}`} className="text-accent hover:underline">
                    {s.submission_id.slice(0, 16)}…
                  </Link>
                  <div className="text-[11px] text-faint">{s.lineage}</div>
                </Td>
                <Td>
                  <StatePill state={s.state} label={s.state_label} />
                </Td>
                <Td className="max-w-md">
                  {s.outcome.summary ? (
                    <span className="text-[12px] leading-snug text-muted">{s.outcome.summary}</span>
                  ) : s.triage_gain_ppm !== null ? (
                    <span className="num">triage {gain(s.triage_gain_ppm)}</span>
                  ) : (
                    <span className="text-faint">in progress</span>
                  )}
                  {s.bound_gain_ppm !== null && (
                    <div className="num mt-1 text-[12px] text-muted">confirmed {gain(s.bound_gain_ppm)}</div>
                  )}
                </Td>
                <Td>
                  {s.outcome.fee ? (
                    <Pill tone={s.outcome.fee === "consumed" ? "neutral" : "warn"}>
                      {s.outcome.fee.replace(/_/g, " ")}
                    </Pill>
                  ) : (
                    <span className="text-faint">—</span>
                  )}
                </Td>
                <Td>
                  <span className="num font-mono text-[11px] text-muted">{s.support_ref}</span>
                </Td>
                <Td>{<TimeAgo at={s.updated_at} />}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
