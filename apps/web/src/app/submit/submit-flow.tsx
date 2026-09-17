"use client";

import { Button, ConfirmButton, CopyRef, ErrorText, useSession } from "@/components/client";
import { Card, Empty, KeyValue, Mono, Notice, Pill, SimulatedTag, Table, Td } from "@/components/ui";
import { ApiFailure, clientFetch } from "@/lib/api";
import { tao, usd } from "@/lib/format";
import clsx from "clsx";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type Fixture = { name: string; title: string; mechanism: string; method: string };
type Preflight = {
  ok: boolean;
  submission_id?: string;
  artifact_sha256: string;
  errors: { code: string; message: string }[];
  changed_paths: string[];
  checked: string[];
  trusted_fixture: string | null;
};
type Quote = {
  status: "quoted" | "waitlisted";
  message?: string;
  quote?: {
    quote_id: string;
    network: string;
    genesis_hash: string;
    recipient: string;
    payer: string;
    amount_rao: number;
    expires_block: number;
    issued_block: number;
    artifact_sha256: string;
    remark: string;
    price_simulated: boolean;
  };
  display?: {
    amount_tao: string;
    target_usd_cents: number;
    fee_usd_cents_at_price: number;
    service_cost_usd_cents: number;
    subsidy_usd_cents: number;
    estimated_network_fee_rao: number;
  };
  capacity?: { reason: string };
};

const STEPS = ["Requirements", "Prepare", "Free checks", "Reserve", "Quote and payment", "Follow"] as const;

export function SubmitFlow({
  capacityOpen,
  capacityReason,
  fixtures,
  demo,
}: {
  capacityOpen: boolean;
  capacityReason: string;
  fixtures: Fixture[];
  demo: boolean;
}) {
  const { session, loaded, reload } = useSession();
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [fixture, setFixture] = useState<string>(fixtures[0]?.name ?? "");
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [payment, setPayment] = useState<{ block_number: number; extrinsic_index: number } | null>(null);
  const [recoverBlock, setRecoverBlock] = useState("");
  const [recoverIndex, setRecoverIndex] = useState("");
  const [error, setError] = useState<ApiFailure | null>(null);
  const [busy, setBusy] = useState(false);
  const [idemKey] = useState(() => Math.random().toString(36).slice(2));

  useEffect(() => {
    if (preflight?.ok && step < 3) setStep(3);
  }, [preflight, step]);

  async function run<T>(fn: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e as ApiFailure);
      return null;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <ol className="flex flex-wrap gap-2" aria-label="Submission steps">
        {STEPS.map((s, i) => (
          <li key={s}>
            <button
              type="button"
              onClick={() => setStep(i)}
              aria-current={i === step ? "step" : undefined}
              className={clsx(
                "rounded-full border px-3 py-1 text-[12px]",
                i === step
                  ? "border-accent bg-accent-quiet text-accent-strong"
                  : i < step
                    ? "border-ok bg-ok-quiet text-ok"
                    : "border-line bg-surface-2 text-muted",
              )}
            >
              {i + 1}. {s}
            </button>
          </li>
        ))}
      </ol>

      {step === 0 && (
        <Card title="What a submission must contain" subtitle="Everything here is checked before you are asked to pay.">
          <Table head={["Requirement", "Value"]}>
            <tr>
              <Td>Format</Td>
              <Td>
                <Mono>tar.gz</Mono> containing <Mono>manifest.json</Mono> and <Mono>patch.diff</Mono>, optional{" "}
                <Mono>NOTICE</Mono> and <Mono>LICENSES/</Mono>
              </Td>
            </tr>
            <tr>
              <Td>Size</Td>
              <Td className="num">20 MiB archive · 80 MiB unpacked · 2,000 entries</Td>
            </tr>
            <tr>
              <Td>Licence</Td>
              <Td>Apache-2.0, MIT or BSD-3-Clause, declared for your code and every third-party component</Td>
            </tr>
            <tr>
              <Td>Paths</Td>
              <Td>Only the profile&apos;s allowed engine paths; model, entrypoint and test paths are refused</Td>
            </tr>
            <tr>
              <Td>Signature</Td>
              <Td>Your hotkey signs the artifact hash. ROOM never asks for a seed phrase or key file</Td>
            </tr>
            <tr>
              <Td>Baseline</Td>
              <Td>Your patch applies to the pinned engine commit; your manifest names the champion you built on</Td>
            </tr>
          </Table>
          <Notice tone="info" title="Which checks are free and which consume the fee">
            <ul className="mt-1 list-disc space-y-1 pl-5">
              <li>Free: format, size, signature, allowed paths, licences, duplicate detection, waiting list.</li>
              <li>
                Paid: everything after your payment is finalized — screening, full evaluation and confirmation.
                The fee is consumed once a screening or evaluation has run, including when the result is a
                rejection caused by your code.
              </li>
              <li>
                Never charged: operator or validator failures, expired quotes, or withdrawal before any GPU work
                starts (that returns a credit).
              </li>
            </ul>
          </Notice>
          <div className="mt-4">
            <Button variant="primary" onClick={() => setStep(1)}>
              Continue
            </Button>
          </div>
        </Card>
      )}

      {step === 1 && (
        <Card title="Prepare and sign your artifact" subtitle="Use the CLI, or a trusted demo fixture in this local build.">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.06em] text-faint">Command line</h3>
          <pre className="mt-2 overflow-x-auto rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3 font-mono text-[12px] leading-relaxed text-muted">
{`# build a signed artifact from your patch and manifest
uv run room-miner pack --patch patch.diff --manifest manifest.json --out artifact.tar.gz

# free checks, then reserve, quote and pay in one guided flow
uv run room-miner submit --artifact artifact.tar.gz --key-uri "//YourDevKey"`}
          </pre>
          <div className="mt-2">
            <CopyRef
              value="uv run room-miner submit --artifact artifact.tar.gz --key-uri '//YourDevKey'"
              label="Copy command"
            />
          </div>

          {demo && fixtures.length > 0 && (
            <div className="mt-5 rounded-[var(--radius-sm)] border border-sim bg-sim-quiet p-4">
              <p className="text-[13px] font-semibold text-sim">
                Demo fixtures <SimulatedTag what="local build only" />
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-muted">
                This build has no isolation backend for untrusted code, so only these repository fixtures can be
                evaluated. Anything else passes the free checks but cannot be quoted.
              </p>
              <div className="mt-3 space-y-2">
                {fixtures.map((f) => (
                  <label
                    key={f.name}
                    className="flex cursor-pointer items-start gap-3 rounded-[var(--radius-sm)] border border-line bg-surface px-3 py-2"
                  >
                    <input
                      type="radio"
                      name="fixture"
                      value={f.name}
                      checked={fixture === f.name}
                      onChange={() => setFixture(f.name)}
                      className="mt-1 accent-[var(--accent)]"
                    />
                    <span>
                      <span className="text-[13px] font-medium text-text">{f.title}</span>
                      <span className="mt-0.5 block text-[12px] text-muted">{f.method}</span>
                      <span className="mt-1 inline-block">
                        <Pill tone="neutral">{f.mechanism.replace(/_/g, " ")}</Pill>
                      </span>
                    </span>
                  </label>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  variant="primary"
                  busy={busy}
                  disabled={!session}
                  onClick={async () => {
                    const r = await run(() =>
                      clientFetch<Preflight>("/v1/demo/submit-fixture", {
                        method: "POST",
                        body: JSON.stringify({ fixture }),
                        idempotencyKey: `${idemKey}-preflight`,
                      }),
                    );
                    if (r) setPreflight(r);
                  }}
                >
                  Build, sign and run free checks
                </Button>
                {!session && loaded && <span className="text-[12px] text-muted">Sign in first.</span>}
              </div>
            </div>
          )}
          <ErrorText error={error} />
        </Card>
      )}

      {step === 2 && !preflight && (
        <Card title="Free checks">
          <Empty title="No result yet">Run the free checks from the previous step.</Empty>
        </Card>
      )}

      {preflight && step >= 2 && step <= 3 && (
        <Card
          title={preflight.ok ? "Free checks passed" : "Free checks found problems"}
          subtitle={`Artifact ${preflight.artifact_sha256.slice(0, 16)}… · no fee was requested`}
        >
          <ul className="space-y-1 text-[13px] text-muted">
            {preflight.checked.map((c) => (
              <li key={c}>✓ {c}</li>
            ))}
          </ul>
          {preflight.errors.length > 0 && (
            <div className="mt-3 space-y-2">
              {preflight.errors.map((e) => (
                <Notice key={e.code} tone="danger" title={e.code.replace(/_/g, " ")}>
                  {e.message}
                </Notice>
              ))}
            </div>
          )}
          {preflight.changed_paths.length > 0 && (
            <div className="mt-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-faint">Changed paths</h3>
              <ul className="mt-1 font-mono text-[11px] text-muted">
                {preflight.changed_paths.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          {preflight.ok && (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                busy={busy}
                onClick={async () => {
                  const r = await run(() =>
                    clientFetch<Quote>(`/v1/miner/submissions/${preflight.submission_id}/reserve`, {
                      method: "POST",
                      body: JSON.stringify({}),
                      idempotencyKey: `${idemKey}-reserve`,
                    }),
                  );
                  if (r) {
                    setQuote(r);
                    setStep(4);
                  }
                }}
              >
                Reserve evaluation capacity
              </Button>
              <Link
                href={`/submissions/${preflight.submission_id}`}
                className="text-[13px] text-accent hover:underline"
              >
                Open this submission
              </Link>
            </div>
          )}
          <ErrorText error={error} />
        </Card>
      )}

      {step === 3 && !preflight && (
        <Card title="Reserve evaluation capacity">
          <Notice tone={capacityOpen ? "ok" : "warn"} title={capacityOpen ? "Capacity is available" : "No paid capacity right now"}>
            {capacityReason}
          </Notice>
          <p className="mt-3 text-[13px] text-muted">Run the free checks first; reservation comes after that.</p>
        </Card>
      )}

      {step === 4 && (
        <Card title="Quote and payment" subtitle="Nothing is charged until you sign; the quote is fixed once issued.">
          {!quote && <Empty title="No quote yet">Reserve capacity in the previous step.</Empty>}
          {quote?.status === "waitlisted" && (
            <Notice tone="warn" title="You are on the free waiting list">
              {quote.message ?? quote.capacity?.reason} No fee was requested. You keep your place and will be
              invited when a slot frees.
            </Notice>
          )}
          {quote?.status === "quoted" && quote.quote && quote.display && (
            <>
              <KeyValue
                rows={[
                  ["Network", <span key="n">{quote.quote.network} <SimulatedTag what="dev chain" /></span>],
                  ["Amount", `${tao(quote.quote.amount_rao)} TAO`],
                  ["Recipient (evaluation wallet)", <Mono key="r">{quote.quote.recipient}</Mono>],
                  ["Paid by", <Mono key="p">{quote.quote.payer}</Mono>],
                  ["Artifact", <Mono key="a">{quote.quote.artifact_sha256.slice(0, 20)}…</Mono>],
                  ["Quote expires", `block ${quote.quote.expires_block} (issued at ${quote.quote.issued_block})`],
                  ["Network transaction fee", `${tao(quote.display.estimated_network_fee_rao)} TAO, paid to the chain, not to ROOM`],
                  ["Service cost basis", `${usd(quote.display.service_cost_usd_cents)} per admission (planning estimate)`],
                  ["Operator subsidy", usd(quote.display.subsidy_usd_cents)],
                ]}
              />
              <Notice tone="info" title="What you are signing">
                One atomic transaction: a transfer of {tao(quote.quote.amount_rao)} TAO to the published
                evaluation wallet, plus a note carrying this quote identifier so the payment can only admit this
                artifact. If any part fails, the whole transaction fails and nothing is taken.
              </Notice>
              <div className="mt-3 rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3">
                <h3 className="text-[12px] font-semibold text-text">Refund rules for this quote</h3>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-[12px] leading-relaxed text-muted">
                  <li>Quote expires before your payment is finalized: refund or credit, your choice.</li>
                  <li>Underpaid, wrong payer or missing note: not admitted; refund on request.</li>
                  <li>Operator or validator failure: refund or credit, and never a second fee.</li>
                  <li>Screening or evaluation runs: the fee is consumed, whatever the result.</li>
                </ul>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3">
                {demo ? (
                  <ConfirmButton
                    variant="primary"
                    label={`Sign and pay ${tao(quote.quote.amount_rao)} TAO (simulated)`}
                    title="Authorize this simulated payment"
                    confirmLabel="Sign and pay"
                    body={
                      <>
                        This signs a simulated transaction on the local dev chain. No real tokens move. After it
                        is finalized your submission is admitted in payment order.
                      </>
                    }
                    onConfirm={async () => {
                      const r = await run(() =>
                        clientFetch<{ block_number: number; extrinsic_index: number }>(
                          `/v1/miner/quotes/${quote.quote!.quote_id}/pay-simulated`,
                          { method: "POST", idempotencyKey: `${idemKey}-pay` },
                        ),
                      );
                      if (r) {
                        setPayment(r);
                        setStep(5);
                        router.refresh();
                      }
                    }}
                  />
                ) : (
                  <Notice tone="warn" title="Signing happens in your wallet">
                    Build the batch transaction shown above in your wallet or with the CLI, then return here and
                    recover it by reference.
                  </Notice>
                )}
                <CopyRef value={quote.quote.remark} label="Copy payment note" />
              </div>
            </>
          )}

          <div className="mt-6 border-t border-line pt-4">
            <h3 className="text-[13px] font-semibold text-text">Already paid? Recover by reference</h3>
            <p className="mt-1 text-[12px] leading-relaxed text-muted">
              If your payment went through but the page was lost, recover it here. This never charges a second
              fee.
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <input
                aria-label="Payment block number"
                value={recoverBlock}
                onChange={(e) => setRecoverBlock(e.target.value.replace(/\D/g, ""))}
                placeholder="block number"
                className="num w-40 rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-2 font-mono text-[12px]"
              />
              <input
                aria-label="Extrinsic index"
                value={recoverIndex}
                onChange={(e) => setRecoverIndex(e.target.value.replace(/\D/g, ""))}
                placeholder="index"
                className="num w-28 rounded-[var(--radius-sm)] border border-line bg-surface-2 px-3 py-2 font-mono text-[12px]"
              />
              <Button
                busy={busy}
                disabled={!recoverBlock || !recoverIndex}
                onClick={async () => {
                  const r = await run(() =>
                    clientFetch<{ outcome: string; reason?: string }>("/v1/miner/payments/recover", {
                      method: "POST",
                      body: JSON.stringify({
                        block_number: Number(recoverBlock),
                        extrinsic_index: Number(recoverIndex),
                      }),
                    }),
                  );
                  if (r) {
                    setPayment({ block_number: Number(recoverBlock), extrinsic_index: Number(recoverIndex) });
                    setStep(5);
                  }
                }}
              >
                Recover payment
              </Button>
            </div>
          </div>
          <ErrorText error={error} />
        </Card>
      )}

      {step === 5 && (
        <Card title="Follow your submission" subtitle="Admission order comes from the finalized payment.">
          {payment ? (
            <KeyValue
              rows={[
                ["Payment block", payment.block_number],
                ["Extrinsic index", payment.extrinsic_index],
                ["What happens next", "The controller verifies finality, issues a signed receipt and queues screening."],
              ]}
            />
          ) : (
            <Empty title="No payment recorded in this session">Use the recovery form if you have paid.</Empty>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {preflight?.submission_id && (
              <Link
                href={`/submissions/${preflight.submission_id}`}
                className="rounded-[var(--radius-sm)] border border-accent bg-accent px-3.5 py-2 text-[13px] font-medium text-[#04201e]"
              >
                Open submission
              </Link>
            )}
            <Link
              href="/submissions"
              className="rounded-[var(--radius-sm)] border border-line-strong bg-surface-2 px-3.5 py-2 text-[13px]"
            >
              All my submissions
            </Link>
          </div>
        </Card>
      )}
    </div>
  );
}
