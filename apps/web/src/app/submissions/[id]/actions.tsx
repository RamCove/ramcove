"use client";

import { ConfirmButton, ErrorText } from "@/components/client";
import { Card } from "@/components/ui";
import { ApiFailure, postJson } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useState } from "react";

const ACTIVE = new Set([
  "preflight_passed",
  "waitlisted",
  "invited",
  "quoted",
  "admitted",
  "screening",
  "eval_queued",
  "evaluating",
  "confirm_queued",
  "confirming",
  "in_review",
]);

export function SubmissionActions({ submissionId, state }: { submissionId: string; state: string }) {
  const router = useRouter();
  const [error, setError] = useState<ApiFailure | null>(null);
  const [grounds, setGrounds] = useState("");
  const canWithdraw = ACTIVE.has(state);
  const canAppeal = state === "review_rejected";
  if (!canWithdraw && !canAppeal) return null;

  return (
    <Card title="Actions" subtitle="Consequential actions always ask for confirmation.">
      <div className="flex flex-wrap gap-2">
        {canWithdraw && (
          <ConfirmButton
            variant="danger"
            label="Withdraw submission"
            title="Withdraw this submission?"
            confirmLabel="Withdraw"
            body={
              <>
                Withdrawing stops the work. If no GPU work has started yet, your fee returns as a credit;
                after screening or evaluation has begun the fee is consumed. This cannot be undone.
              </>
            }
            onConfirm={async () => {
              try {
                await postJson<"WithdrawIn">(`/v1/miner/submissions/${submissionId}/withdraw`, {
                  reason: "withdrawn from the web app",
                });
                router.refresh();
              } catch (e) {
                setError(e as ApiFailure);
              }
            }}
          />
        )}
      </div>

      {canAppeal && (
        <div className="mt-3">
          <label htmlFor="grounds" className="text-[12px] font-medium text-muted">
            Appeal the review decision (7-day window). Explain the grounds in at least 20 characters.
          </label>
          <textarea
            id="grounds"
            value={grounds}
            onChange={(e) => setGrounds(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-2 text-[13px] text-text"
          />
          <div className="mt-2">
            <ConfirmButton
              label="Submit appeal"
              title="Submit this appeal?"
              confirmLabel="Submit appeal"
              disabled={grounds.trim().length < 20}
              body="Your appeal is decided by someone who was not part of the disputed decision."
              onConfirm={async () => {
                try {
                  await postJson<"AppealIn">(`/v1/miner/submissions/${submissionId}/appeal`, { grounds });
                  setGrounds("");
                  router.refresh();
                } catch (e) {
                  setError(e as ApiFailure);
                }
              }}
            />
          </div>
        </div>
      )}
      <ErrorText error={error} />
    </Card>
  );
}
