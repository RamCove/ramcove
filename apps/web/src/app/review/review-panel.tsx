"use client";

import { Button, ConfirmButton, ErrorText } from "@/components/client";
import { Card, Empty, Notice, Pill } from "@/components/ui";
import { ApiFailure, clientFetch, postJson } from "@/lib/api";
import { gain, when } from "@/lib/format";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

type Criteria = { id: string; title: string }[];

export function ReviewPanel({
  queue,
  appeals,
}: {
  queue: {
    criteria: Criteria;
    items: {
      review_id: string;
      submission_id: string;
      author: string;
      lineage: string;
      bound_gain_ppm: number | null;
      opened_at: string;
      due_at: string;
      is_own_submission: boolean;
    }[];
  };
  appeals: {
    id: string;
    submission_id: string;
    grounds: string;
    appellant: string;
    disputed_decider: string | null;
    due_at: string;
    may_decide: boolean;
  }[];
}) {
  const router = useRouter();
  const [results, setResults] = useState<Record<string, boolean>>({});
  const [reasons, setReasons] = useState("");
  const [active, setActive] = useState<string | null>(queue.items[0]?.review_id ?? null);
  const [error, setError] = useState<ApiFailure | null>(null);
  const item = queue.items.find((i) => i.review_id === active) ?? null;
  const allSet = queue.criteria.every((c) => c.id in results);
  const failed = queue.criteria.filter((c) => results[c.id] === false).map((c) => c.id);

  async function decide(decision: "approve" | "reject", conflict = false) {
    setError(null);
    try {
      await postJson<"DecisionIn">(`/v1/review/${active}/decide`, {
        decision,
        reasons,
        criteria: results,
        conflict,
      });
      setResults({});
      setReasons("");
      router.refresh();
    } catch (e) {
      setError(e as ApiFailure);
    }
  }

  return (
    <div className="grid items-start gap-5 lg:grid-cols-[1fr_1.3fr]">
      <Card title="Waiting for review">
        {queue.items.length === 0 ? (
          <Empty title="Nothing to review">Reviews open when a challenger clears the replacement rule.</Empty>
        ) : (
          <ul className="space-y-2">
            {queue.items.map((i) => (
              <li key={i.review_id}>
                <button
                  type="button"
                  onClick={() => setActive(i.review_id)}
                  aria-current={i.review_id === active}
                  className={
                    "w-full rounded-[var(--radius-sm)] border px-3 py-2 text-left " +
                    (i.review_id === active
                      ? "border-accent bg-accent-quiet"
                      : "border-line bg-surface-2 hover:bg-surface-3")
                  }
                >
                  <span className="block text-[13px] text-text">{i.lineage}</span>
                  <span className="num block text-[12px] text-muted">
                    confirmed {gain(i.bound_gain_ppm)} · due {when(i.due_at)}
                  </span>
                  {i.is_own_submission && (
                    <span className="mt-1 inline-block">
                      <Pill tone="danger">your own submission — recuse</Pill>
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="space-y-5">
        <Card
          title={item ? `Review ${item.submission_id.slice(0, 14)}…` : "Review"}
          subtitle={item ? `Author ${item.author.slice(0, 10)}… · lineage ${item.lineage}` : undefined}
          actions={
            item && (
              <Link href={`/submissions/${item.submission_id}`} className="text-[13px] text-accent hover:underline">
                Open evidence
              </Link>
            )
          }
        >
          {!item ? (
            <Empty title="Select a review" />
          ) : item.is_own_submission ? (
            <Notice tone="danger" title="You cannot review your own submission">
              Another reviewer must decide this one.
            </Notice>
          ) : (
            <>
              <ul className="space-y-2">
                {queue.criteria.map((c) => (
                  <li key={c.id} className="flex items-center justify-between gap-3 border-b border-line py-2">
                    <span className="text-[13px] text-text">{c.title}</span>
                    <span className="flex shrink-0 gap-1">
                      <Button
                        size="sm"
                        variant={results[c.id] === true ? "primary" : "secondary"}
                        onClick={() => setResults((r) => ({ ...r, [c.id]: true }))}
                      >
                        Pass
                      </Button>
                      <Button
                        size="sm"
                        variant={results[c.id] === false ? "danger" : "secondary"}
                        onClick={() => setResults((r) => ({ ...r, [c.id]: false }))}
                      >
                        Fail
                      </Button>
                    </span>
                  </li>
                ))}
              </ul>
              <label htmlFor="reasons" className="mt-4 block text-[12px] font-medium text-muted">
                Reasons and evidence {failed.length > 0 && "(required for a rejection, at least 20 characters)"}
              </label>
              <textarea
                id="reasons"
                rows={3}
                value={reasons}
                onChange={(e) => setReasons(e.target.value)}
                className="mt-1 w-full rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-2 text-[13px]"
              />
              <div className="mt-3 flex flex-wrap gap-2">
                <ConfirmButton
                  variant="primary"
                  label="Approve for promotion"
                  title="Approve this submission?"
                  confirmLabel="Approve"
                  disabled={!allSet || failed.length > 0}
                  body="Approval does not crown it immediately: it still waits for earlier admissions and for the author's hotkey to be registered."
                  onConfirm={() => decide("approve")}
                />
                <ConfirmButton
                  variant="danger"
                  label="Reject"
                  title="Reject this submission?"
                  confirmLabel="Reject"
                  disabled={!allSet || failed.length === 0 || reasons.trim().length < 20}
                  body={`Rejection cites: ${failed.join(", ") || "no failed criterion selected"}. The author may appeal within 7 days.`}
                  onConfirm={() => decide("reject")}
                />
                <Button variant="quiet" onClick={() => decide("approve", true)}>
                  Declare a conflict and recuse
                </Button>
              </div>
              <ErrorText error={error} />
            </>
          )}
        </Card>

        <Card title="Appeals" subtitle="Decided by someone who was not part of the disputed decision.">
          {appeals.length === 0 ? (
            <Empty title="No open appeals" />
          ) : (
            <ul className="space-y-3">
              {appeals.map((a) => (
                <li key={a.id} className="rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link href={`/submissions/${a.submission_id}`} className="text-[13px] text-accent hover:underline">
                      {a.submission_id.slice(0, 14)}…
                    </Link>
                    <Pill tone={a.may_decide ? "ok" : "warn"}>
                      {a.may_decide ? "you may decide" : "you must recuse"}
                    </Pill>
                    <span className="text-[12px] text-muted">due {when(a.due_at)}</span>
                  </div>
                  <p className="mt-2 text-[12px] leading-relaxed text-muted">{a.grounds}</p>
                  {a.may_decide && (
                    <div className="mt-2 flex gap-2">
                      <ConfirmButton
                        size="sm"
                        label="Uphold"
                        title="Uphold this appeal?"
                        confirmLabel="Uphold"
                        body="The submission returns to review with a fresh review record."
                        onConfirm={async () => {
                          await postJson<"AppealDecisionIn">(`/v1/appeals/${a.id}/decide`, {
                            upheld: true,
                            reason: "Appeal upheld after panel review.",
                          });
                          router.refresh();
                        }}
                      />
                      <ConfirmButton
                        size="sm"
                        variant="danger"
                        label="Dismiss"
                        title="Dismiss this appeal?"
                        confirmLabel="Dismiss"
                        body="The original rejection stands and is published with the reason."
                        onConfirm={async () => {
                          await postJson<"AppealDecisionIn">(`/v1/appeals/${a.id}/decide`, {
                            upheld: false,
                            reason: "Appeal dismissed after panel review.",
                          });
                          router.refresh();
                        }}
                      />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
