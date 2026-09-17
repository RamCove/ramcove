"use client";

import { Button, ConfirmButton, ErrorText } from "@/components/client";
import { Card, Notice, Pill, Table, Td } from "@/components/ui";
import { ApiFailure, clientFetch } from "@/lib/api";
import { tao } from "@/lib/format";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function OperatorControls({ paused }: { paused: boolean }) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [rollbackReason, setRollbackReason] = useState("");
  const [deliberate, setDeliberate] = useState(false);
  const [error, setError] = useState<ApiFailure | null>(null);
  const [verify, setVerify] = useState<{ ok: boolean; events_checked: number } | null>(null);

  async function call<T>(path: string, body?: unknown) {
    setError(null);
    try {
      const r = await clientFetch<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      router.refresh();
      return r;
    } catch (e) {
      setError(e as ApiFailure);
      return null;
    }
  }

  return (
    <Card title="Controls" subtitle="Every action records a reason in the audit trail.">
      <div className="grid gap-5 lg:grid-cols-2">
        <div>
          <label htmlFor="intake-reason" className="text-[12px] font-medium text-muted">
            Reason for pausing or resuming paid admissions
          </label>
          <input
            id="intake-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. worker maintenance window"
            className="mt-1 w-full rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-2 text-[13px]"
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <ConfirmButton
              label={paused ? "Resume paid admissions" : "Pause paid admissions"}
              title={paused ? "Resume admissions?" : "Pause admissions?"}
              confirmLabel={paused ? "Resume" : "Pause"}
              variant={paused ? "primary" : "danger"}
              disabled={reason.trim().length < 5}
              body={
                paused
                  ? "New quotes will be issued again while capacity allows."
                  : "No new quotes will be issued. Work already paid for continues, and the waiting list still accepts entries."
              }
              onConfirm={async () => {
                await call("/v1/operator/intake", { paused: !paused, reason });
                setReason("");
              }}
            />
            <Button
              onClick={async () => {
                const r = await call<{ ok: boolean; events_checked: number }>("/v1/demo/tick");
                if (r) router.refresh();
              }}
            >
              Run one controller tick
            </Button>
            <Button
              variant="quiet"
              onClick={async () => {
                setError(null);
                try {
                  const r = await clientFetch<{ ok: boolean; events_checked: number }>("/v1/operator/audit/verify");
                  setVerify(r);
                } catch (e) {
                  setError(e as ApiFailure);
                }
              }}
            >
              Verify the audit chain
            </Button>
          </div>
          {verify && (
            <p className="mt-2 text-[13px]">
              <Pill tone={verify.ok ? "ok" : "danger"}>
                {verify.ok ? "audit chain intact" : "audit chain broken"}
              </Pill>{" "}
              <span className="num text-muted">{verify.events_checked} events checked</span>
            </p>
          )}
        </div>

        <div>
          <label htmlFor="rollback-reason" className="text-[12px] font-medium text-muted">
            Emergency rollback of the current champion
          </label>
          <input
            id="rollback-reason"
            value={rollbackReason}
            onChange={(e) => setRollbackReason(e.target.value)}
            placeholder="reason recorded in the audit trail"
            className="mt-1 w-full rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-2 text-[13px]"
          />
          <label className="mt-2 flex items-center gap-2 text-[12px] text-muted">
            <input
              type="checkbox"
              checked={deliberate}
              onChange={(e) => setDeliberate(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            The flaw looks deliberate (the lineage is excluded)
          </label>
          <div className="mt-2">
            <ConfirmButton
              variant="danger"
              label="Suspend and roll back"
              title="Roll back to the previous reviewed stack?"
              confirmLabel="Roll back"
              disabled={rollbackReason.trim().length < 10}
              body={
                <>
                  The current champion is suspended and kept with its evidence. The previous reviewed stack
                  becomes current under a new version number, so every pending comparison is rebased. Weight
                  goes to no winner until a challenger qualifies.
                </>
              }
              onConfirm={async () => {
                await call("/v1/operator/champion/rollback", { reason: rollbackReason, deliberate });
                setRollbackReason("");
              }}
            />
          </div>
          <Notice tone="warn" title="What this console cannot do">
            It cannot set a champion by hand, edit a measured score, or delete evidence. Rollback preserves the
            suspended version and the audit trail.
          </Notice>
        </div>
      </div>
      <ErrorText error={error} />
    </Card>
  );
}

export function RefundControls({
  refunds,
}: {
  refunds: { id: string; status: string; amount_rao: number; hotkey: string; reason: string; simulated: boolean }[];
}) {
  const router = useRouter();
  const [error, setError] = useState<ApiFailure | null>(null);
  async function act(id: string, action: "approve" | "execute") {
    setError(null);
    try {
      await clientFetch(`/v1/operator/refunds/${id}/${action}`, { method: "POST" });
      router.refresh();
    } catch (e) {
      setError(e as ApiFailure);
    }
  }
  return (
    <>
      <Table head={["Hotkey", "Amount", "Reason", "Status", "Action"]}>
        {refunds.map((r) => (
          <tr key={r.id}>
            <Td>{r.hotkey.slice(0, 10)}…</Td>
            <Td className="num">{tao(r.amount_rao)}</Td>
            <Td className="max-w-xs text-[12px] text-muted">{r.reason}</Td>
            <Td>
              <Pill tone={r.status === "confirmed" ? "ok" : r.status === "requested" ? "warn" : "info"}>
                {r.status}
              </Pill>
            </Td>
            <Td>
              {r.status === "requested" && (
                <ConfirmButton
                  size="sm"
                  label="Approve"
                  title="Approve this refund?"
                  confirmLabel="Approve"
                  body="Approval records the decision. Sending the funds is a separate, idempotent step."
                  onConfirm={() => act(r.id, "approve")}
                />
              )}
              {r.status === "approved" && (
                <ConfirmButton
                  size="sm"
                  variant="primary"
                  label={r.simulated ? "Send (simulated)" : "Send"}
                  title="Send this refund?"
                  confirmLabel="Send"
                  body={
                    r.simulated
                      ? "This sends a simulated transfer on the dev chain. No real tokens move."
                      : "This requires an authorized signer, which this build does not include."
                  }
                  onConfirm={() => act(r.id, "execute")}
                />
              )}
            </Td>
          </tr>
        ))}
      </Table>
      <ErrorText error={error} />
    </>
  );
}
