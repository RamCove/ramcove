import {
  Card,
  Mono,
  Notice,
  PageHeader,
  Table,
  Td,
  Term,
} from "@/components/ui";
import { WHITEPAPER_PDF } from "@/lib/site";
import type { Metadata } from "next";
import Link from "next/link";
import { DocsTabs } from "@/components/docs-tabs";

export const metadata: Metadata = { title: "Docs" };

/** The eight steps, their GPU cost and what each one is for. The dashboard shows the same list, built
 *  from the rules the evaluator runs; this page repeats it with the reason for each step. */
const WORKFLOW: { name: string; cost: string; what: string; why: string }[] = [
  {
    name: "Free checks",
    cost: "no GPU",
    what: "Signature, manifest, declared paths, licences, size and duplicates.",
    why: "Nothing is charged and no code runs, so a formatting mistake never costs a fee.",
  },
  {
    name: "Quote, payment, queue place",
    cost: "books 2.41 GPU-h",
    what: "A flat 0.1 TAO. The finalized block and index of the payment fix the order.",
    why: "Paying fixes a place in line, so finishing early never overtakes an earlier payment.",
  },
  {
    name: "Screening",
    cost: "0.17 GPU-h",
    what: "Isolated build, engine start, 200 bank questions and the memory ceiling. Speed is not judged.",
    why: "Ten minutes rejects what cannot build, start or answer, before an hour of measurement.",
  },
  {
    name: "Question quality",
    cost: "1.00 GPU-h",
    what: "All 4,000 bank questions, against the champion's answers to the same questions and a frozen reference.",
    why: "Serving more requests by answering them worse is not an improvement, and this ends it before any load test.",
  },
  {
    name: "Capacity reading",
    cost: "~1.08 GPU-h",
    what: "Eight-minute runs from the champion's fixed score, stepping up 3% after each run that passes the gates.",
    why: "The champion was measured once, when it was crowned, so only the challenger has to be measured now.",
  },
  {
    name: "The rule",
    cost: "no GPU",
    what: "At or below 5% loses, at or above 9% wins, in between one more reading decides on the average.",
    why: "A margin wide enough to clear measurement noise, and a near-tie keeps the incumbent.",
  },
  {
    name: "Winner checks",
    cost: "3.57 GPU-h, reserve",
    what: "Context bands, memory evidence at a 25% smaller cache budget, short requests, real conversations, an hour-long soak.",
    why: "Each answers something one eight-minute reading cannot, and they only run for a winner.",
  },
  {
    name: "Promotion",
    cost: "6.51 GPU-h, reserve",
    what: "Automatic unless a check flagged it, in payment order. The champion's code is published and its score measured again on every worker.",
    why: "The next challenger is judged against a fresh number measured on the worker that will judge it.",
  },
];

/** Keyed by the outcome code the API actually writes, so a submission page can link straight here. */
const FAILURES: [string, string, string][] = [
  [
    "rejected_preflight",
    "A free check failed: format, signature, path, licence or a duplicate patch.",
    "Fix the reported item and run the checks again. No fee was taken.",
  ],
  [
    "screen_build_failure",
    "The patch did not build on two clean isolated builds.",
    "Build against the pinned engine commit locally first. The fee is consumed.",
  ],
  [
    "screen_no_start",
    "The engine did not start within five minutes.",
    "Check your change against the pinned engine arguments. The fee is consumed.",
  ],
  [
    "screen_memory_ceiling",
    "Peak GPU memory passed the profile ceiling at low load.",
    "Bring peak memory under the ceiling before resubmitting.",
  ],
  [
    "screen_gross_accuracy",
    "Smoke answers were far below the champion's on the same questions.",
    "Check that your change does not break correctness before resubmitting.",
  ],
  [
    "quality_failed",
    "Answers fell below the champion, the frozen reference or an absolute floor.",
    "Fix the accuracy loss first. Speed never makes up for wrong answers.",
  ],
  [
    "margin_not_cleared",
    "The gain over the champion's fixed score did not exceed the margin. For a close first reading, neither did the average of the two.",
    "A near-tie keeps the incumbent. Improve the method rather than resubmitting the same code.",
  ],
  [
    "winner_check_failed",
    "The gain was there, but a context band, the memory evidence, the short-request control, the multi-turn check or the soak failed.",
    "The submission page names the check and what it measured. RamCove rewards memory-driven capacity; a pure speedup is out of scope.",
  ],
  [
    "champion_changed",
    "Another submission was crowned first, and over the new champion your measured gain is below the margin. Nothing was measured again.",
    "Build on the new champion and submit again.",
  ],
  [
    "not_reproduced",
    "A second validator repeated the reading on its own worker and did not clear the margin.",
    "Both readings are published on the submission page.",
  ],
  [
    "review_rejected",
    "A person reviewed your flagged winner and a published criterion failed.",
    "The decision cites the criterion. You may appeal within 7 days.",
  ],
  [
    "registration_expired",
    "The winning hotkey was not registered on the subnet within the grace period.",
    "The submission page shows the deadline while it runs. Register the hotkey before it passes.",
  ],
  [
    "operator_failure",
    "Infrastructure, quorum or deadline failure on our side.",
    "Your fee returns as a refund or credit. Nothing is charged twice.",
  ],
  [
    "quote_expired",
    "The quote was not paid before it expired.",
    "Ask for a new quote. Nothing was charged.",
  ],
  [
    "late_payment",
    "The payment was finalized after the quote had expired.",
    "The payment returns as a refund or credit.",
  ],
];

export default function DocsPage() {
  return (
    <div className="min-w-0 space-y-8">
      <DocsTabs active="guide" />
      <PageHeader
        eyebrow="Documentation"
        title="How RamCove works"
        lede="How miners submit and how validators measure, both from the command line, and what each failure means. The full protocol specification and the runbooks live in the repository."
      />

      <Notice tone="sim" title="Everything here runs on a simulation">
        The chain, the randomness beacon, the workers and the payments are
        simulated and labelled. No GPU is measured, no tokens move, and mainnet
        writes are disabled.
      </Notice>

      <Card
        id="workflow"
        eyebrow="The whole path"
        title="How a submission is judged"
        subtitle="Eight steps, in this order. What each one is for, and what it costs in GPU time."
        className="scroll-mt-24"
      >
        <ol className="grid gap-px overflow-hidden rounded-[var(--radius-card)] border border-line bg-line md:grid-cols-2">
          {WORKFLOW.map((w, i) => (
            <li key={w.name} className="bg-surface p-4">
              <div className="flex items-baseline gap-2">
                <span className="num font-mono text-[12px] text-faint">
                  {i + 1}
                </span>
                <span className="font-medium text-text">{w.name}</span>
                <span className="num ml-auto font-mono text-[11.5px] text-muted">
                  {w.cost}
                </span>
              </div>
              <p className="mt-1.5 text-[13px] leading-snug text-muted">
                {w.what}
              </p>
              <p className="mt-1.5 text-[12.5px] leading-snug text-faint">
                {w.why}
              </p>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-[13px] leading-relaxed text-muted">
          A miner&apos;s fee books screening plus one evaluation: 2.41
          GPU-hours. A winner&apos;s extra checks (3.57) and the new
          champion&apos;s fixed score (6.51 per worker) are paid from the
          published reserve, not from the fee. The{" "}
          <Link
            href="/dashboard#workflow"
            className="text-accent hover:underline"
          >
            dashboard
          </Link>{" "}
          shows where each paid submission is in this path right now; Section 5
          of the{" "}
          <a
            href={WHITEPAPER_PDF}
            target="_blank"
            rel="noreferrer"
            className="text-accent hover:underline"
          >
            whitepaper
          </a>{" "}
          explains why each step is there.
        </p>
      </Card>

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Card
          id="miners"
          eyebrow="For miners"
          title="Submit from the command line"
          subtitle="There is nothing to sign in to on this site. Your hotkey signs each step inside the ramcove-miner tool."
          className="scroll-mt-24 lg:col-span-2"
        >
          <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
            <ol className="list-decimal space-y-2 pl-5 text-[13px] leading-relaxed text-muted">
              <li>
                Download the current champion&apos;s code with{" "}
                <Mono>champion-code</Mono>: only its patches, a few kilobytes.
                Apply them to the engine at the commit shown in the rules and
                build your change on top, inside the allowed paths shown in the{" "}
                <Link
                  href="/docs/rules"
                  className="text-accent hover:underline"
                >
                  rules
                </Link>
                . While version 0 holds the crown there are no patches: the
                champion is the unmodified engine.
              </li>
              <li>
                <Mono>pack</Mono> turns your patch and manifest into a
                reproducible artifact.
              </li>
              <li>
                <Mono>preflight</Mono> runs the free checks. They never cost
                anything and never execute your code.
              </li>
              <li>
                <Mono>submit</Mono> reserves capacity and shows the quote: a
                flat 0.1 TAO, the recipient, the expiry and the refund rules.
                Nothing is paid until you confirm. If the queue is full you join
                the free waiting list. There is no daily limit; you may have one
                active submission per hotkey, and one per lineage name.
              </li>
              <li>
                Your place in line is the finalized block and index of your
                payment.
              </li>
              <li>
                Screening (10 minutes), then one evaluation against the
                champion&apos;s fixed score. The questions come from the
                owner&apos;s question bank for the week, the same for every
                submission that week. A winner is promoted automatically unless
                a check flags it for a person. Follow it with{" "}
                <Mono>status</Mono> or on the{" "}
                <Link href="/dashboard" className="text-accent hover:underline">
                  dashboard
                </Link>
                .
              </li>
            </ol>
            <pre className="overflow-x-auto rounded-[var(--radius-sm)] border border-line bg-surface-2 p-4 font-mono text-[12px] leading-relaxed text-muted">
              {`# the champion's code: its patches, checked against their hashes
uv run ramcove-miner champion-code --out champion/

# build a reproducible artifact from your patch
uv run ramcove-miner pack --patch patch.diff --manifest manifest.json

# the free checks: no fee, your code is not run
uv run ramcove-miner preflight --artifact artifact.tar.gz --key-uri //Dev

# checks, reserve, quote; pays only after you confirm
uv run ramcove-miner submit --artifact artifact.tar.gz --key-uri //Dev

# follow a submission
uv run ramcove-miner status --submission sub_...

# lost track of a payment? recover it, never charged twice
uv run ramcove-miner recover --block N --index I --key-uri //Dev`}
            </pre>
          </div>
          <p className="mt-4 text-[12.5px] leading-relaxed text-faint">
            In this build <Mono>--key-uri</Mono> takes a development key and
            works only on the simulated network; a wallet signer for a real
            network is not included. The tool talks to the API given by{" "}
            <Mono>--api</Mono> (default <Mono>http://127.0.0.1:8787</Mono>). The
            hosted site does not take submissions from the internet yet, so run
            the stack locally to try it.
          </p>
        </Card>

        <Card
          id="validators"
          eyebrow="For validators"
          title="Run the validator software"
          subtitle="Validators do not sign in here either. They run evaluation workers that sign their own requests."
          className="scroll-mt-24 lg:col-span-2"
        >
          <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
            <ul className="list-disc space-y-2 pl-5 text-[13px] leading-relaxed text-muted">
              <li>
                A worker is one physical host with one whole GPU of the
                profile&apos;s type (an H100 SXM in the first profile), no MIG
                and no other workload during measurement.
              </li>
              <li>
                <Mono>ramcove-worker</Mono> takes work from the API, runs it
                inside its isolation provider and reports signed results. It
                holds no database credentials, chain keys or tokens.
              </li>
              <li>
                Candidates run in a hardware-virtualized VM with the GPU passed
                through, no network, and a trusted host-side measurement agent.
              </li>
              <li>
                &quot;Online&quot; and &quot;safe and ready&quot; are different
                states. A worker that cannot prove its isolation is never given
                untrusted code. Each worker&apos;s state is on the{" "}
                <Link href="/status" className="text-accent hover:underline">
                  status page
                </Link>
                .
              </li>
              <li>
                Each worker records the champion&apos;s score once, when it is
                crowned. Once independent validators take over, a second
                validator reproduces each winner once.
              </li>
            </ul>
            <pre className="overflow-x-auto rounded-[var(--radius-sm)] border border-line bg-surface-2 p-4 font-mono text-[12px] leading-relaxed text-muted">
              {`# one worker per GPU host
export RAMCOVE_API_ORIGIN=http://127.0.0.1:8787
export RAMCOVE_WORKER_ID=w-1
export RAMCOVE_WORKER_KEY_URI=<the worker's signing key>

# the VM isolation provider for real measurement
export RAMCOVE_WORKER_PROVIDER=vfio-vm
export RAMCOVE_GPU_BDF=<PCI address of the GPU>
export RAMCOVE_VM_IMAGE_SHA256=<pinned VM image>
export RAMCOVE_MEASUREMENT_AGENT_SOCKET=<agent socket>

uv run ramcove-worker`}
            </pre>
          </div>
          <p className="mt-4 text-[12.5px] leading-relaxed text-faint">
            In this build the VM provider runs its readiness checks and then
            fails closed: real GPU execution is not implemented yet. The demo
            workers use the simulated provider, which only replays trusted
            fixtures, and weights are proposed but never set on a chain.
          </p>
        </Card>

        <Card
          title="Terms you will meet"
          subtitle="Plain meanings, in the order you meet them."
        >
          <Table head={["Term", "What it means"]}>
            <tr>
              <Td>
                <Term
                  term="Qualified serving capacity"
                  plain="The comparison quantity RamCove measures"
                >
                  Qualified serving capacity
                </Term>
              </Td>
              <Td>
                The highest steady request rate where every answer still meets
                quality, time and resource limits.
              </Td>
            </tr>
            <tr>
              <Td>TTFT</Td>
              <Td>Time until the first answer token reaches the user.</Td>
            </tr>
            <tr>
              <Td>TPOT</Td>
              <Td>
                Mean time between output tokens once the answer has started.
              </Td>
            </tr>
            <tr>
              <Td>KV cache</Td>
              <Td>
                The per-conversation working memory a model keeps on the GPU. It
                is what RamCove is about.
              </Td>
            </tr>
            <tr>
              <Td>Question bank</Td>
              <Td>
                The owner&apos;s secret questions for one week: screening,
                quality and the traffic scripts. Its fingerprint is published
                before the week starts and the bank itself after it ends.
              </Td>
            </tr>
            <tr>
              <Td>Fixed score</Td>
              <Td>
                The champion&apos;s capacity, recorded once per worker when it
                was crowned. Challengers are compared with it; it is never
                measured again.
              </Td>
            </tr>
            <tr>
              <Td>Reading</Td>
              <Td>
                One capacity search: the highest rate on a fixed grid at which
                the challenger still meets every limit. A close first reading
                gets a second.
              </Td>
            </tr>
            <tr>
              <Td>Flagged</Td>
              <Td>
                An automatic check, such as native code or third-party
                components, that sends a winner to a person before promotion.
              </Td>
            </tr>
            <tr>
              <Td>Re-compare</Td>
              <Td>
                If another submission is crowned while yours waits, your
                measured gain is set against the new champion by arithmetic.
                Your place and fee are kept.
              </Td>
            </tr>
            <tr>
              <Td>Admission key</Td>
              <Td>
                The finalized block and index of your payment. It fixes
                promotion order.
              </Td>
            </tr>
          </Table>
        </Card>

        <Card
          title="Why did my submission fail?"
          subtitle="Each outcome on a submission page links to its row here."
        >
          <Table head={["Outcome", "What it means", "What to do"]}>
            {FAILURES.map(([code, meaning, action]) => (
              <tr
                key={code}
                id={`outcome-${code}`}
                className="scroll-mt-24 target:bg-accent-quiet"
              >
                <Td className="font-mono text-[12.5px] font-medium">{code}</Td>
                <Td className="text-muted">{meaning}</Td>
                <Td className="text-muted">{action}</Td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card
          title="Local development"
          subtitle="Run the whole stack on one machine."
        >
          <pre className="overflow-x-auto rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3 font-mono text-[12px] leading-relaxed text-muted">
            {`make setup      # install Python and web dependencies
make db         # start PostgreSQL and apply migrations
make seed       # labelled demo dataset
make dev        # API, controller, two workers and the web app
make test-all   # unit and database-backed tests
make reset      # wipe and reseed the demo data`}
          </pre>
          <p className="mt-3 text-[13px] leading-relaxed text-muted">
            The repository holds the corrected protocol specification, the
            requirements and acceptance matrix, architecture decisions, the
            threat model, the integration-readiness checklist and the runbooks
            for deployment, backup, recovery, refunds, rollback and incidents.
          </p>
        </Card>

        <Card
          title="Supported software package"
          subtitle="What a customer would receive. Not sold in this build."
        >
          <p className="text-[13px] leading-relaxed text-muted">
            Approved champions are merged into an open reference stack and
            released on a quarterly cadence after a soak test, as a validated
            build for one profile with a capacity test on the customer&apos;s
            own hardware. RamCove does not route production requests to miners
            and offers no inference API. There is no customer billing portal in
            this build, and no customer, revenue or partnership exists.
          </p>
        </Card>
      </div>
    </div>
  );
}
