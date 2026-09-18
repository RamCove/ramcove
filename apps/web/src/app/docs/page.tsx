import { Card, Mono, Notice, PageHeader, Table, Td, Term } from "@/components/ui";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Docs" };

const FAILURES: [string, string, string][] = [
  ["rejected in the free checks", "Format, signature, path, licence or duplicate problem.", "Fix the reported item and run the checks again. No fee was taken."],
  ["screen build failure", "The patch did not build on two clean isolated builds.", "Build against the pinned engine commit locally first. The fee is consumed."],
  ["screen gross accuracy", "Smoke answers were far below the champion's.", "Check that your change does not break correctness before resubmitting."],
  ["not a potential winner", "Gates failed, or the triage gain was below the margin.", "Read the failed gate on the submission page; each names what it measured."],
  ["margin not cleared", "The confirmed lower bound did not exceed the margin.", "A near-tie keeps the incumbent. Improve the method rather than resubmitting the same code."],
  ["memory evidence", "The gain did not hold under a smaller cache budget, or the memory probe showed no change.", "RamCove rewards memory-driven capacity; a pure speedup is out of scope."],
  ["review rejected", "A published criterion failed.", "The decision cites the criterion. You may appeal within 7 days."],
  ["operator failure", "Infrastructure, quorum or deadline failure on our side.", "Your fee returns as a refund or credit. Nothing is charged twice."],
  ["registration expired", "The winning hotkey was not registered within the grace period.", "Register the hotkey before the deadline shown on the submission."],
];

export default function DocsPage() {
  return (
    <div className="min-w-0 space-y-8">
      <PageHeader
        eyebrow="Documentation"
        title="How RamCove works"
        lede="What a submission must contain, how it is measured, and what each failure means. The full protocol specification and the runbooks live in the repository."
      />

      <Notice tone="sim" title="This build is a local development environment">
        The chain, the randomness beacon, the workers and the payments are simulated and labelled. No GPU is
        measured, no tokens move, and mainnet writes are disabled.
      </Notice>

      <div className="grid items-start gap-5 lg:grid-cols-2">
        <Card title="For miners" subtitle="From a patch to a champion.">
          <ol className="list-decimal space-y-2 pl-5 text-[13px] leading-relaxed text-muted">
            <li>
              Build your change against the pinned engine commit shown on the{" "}
              <Link href="/competition" className="text-accent hover:underline">
                profile page
              </Link>
              , inside the allowed paths.
            </li>
            <li>
              Pack and sign: <Mono>uv run ramcove-miner pack</Mono> then <Mono>uv run ramcove-miner submit</Mono>.
            </li>
            <li>Free checks run first. They never cost anything and never execute your code.</li>
            <li>If capacity exists you get a quote. Otherwise you join the free waiting list.</li>
            <li>Pay in TAO. Your place in line is the finalized payment block and index.</li>
            <li>
              Screening, full evaluation, then five paired blocks against the frozen champion, then review.
            </li>
          </ol>
        </Card>

        <Card title="For validators" subtitle="Running workers that are actually safe to evaluate with.">
          <ul className="list-disc space-y-2 pl-5 text-[13px] leading-relaxed text-muted">
            <li>
              A worker is one physical host with one whole H100 SXM, no MIG and no other workload during
              measurement.
            </li>
            <li>
              Candidates run in a hardware-virtualized VM with the GPU passed through, no network, and a
              trusted host-side measurement agent.
            </li>
            <li>
              The worker signs every API request with its own key. It holds no database credentials, chain keys
              or tokens.
            </li>
            <li>
              &quot;Online&quot; and &quot;safe and ready&quot; are different states. A worker that cannot prove
              its isolation is never given untrusted code.
            </li>
            <li>Confirmation blocks are spread across separately provisioned workers, and later across validators.</li>
          </ul>
        </Card>

        <Card title="Terms you will meet" subtitle="Plain meanings, in the order you meet them.">
          <Table head={["Term", "What it means"]}>
            <tr>
              <Td>
                <Term term="Qualified serving capacity" plain="The comparison quantity RamCove measures">
                  Qualified serving capacity
                </Term>
              </Td>
              <Td>The highest steady request rate where every answer still meets quality, time and resource limits.</Td>
            </tr>
            <tr>
              <Td>TTFT</Td>
              <Td>Time until the first answer token reaches the user.</Td>
            </tr>
            <tr>
              <Td>TPOT</Td>
              <Td>Mean time between output tokens once the answer has started.</Td>
            </tr>
            <tr>
              <Td>KV cache</Td>
              <Td>The per-conversation working memory a model keeps on the GPU. It is what RamCove is about.</Td>
            </tr>
            <tr>
              <Td>Paired block</Td>
              <Td>One re-imaged worker session that measures the champion and the challenger on the same fresh tests.</Td>
            </tr>
            <tr>
              <Td>Triage versus confirmation</Td>
              <Td>Triage is one estimate that decides whether to spend more; only confirmation blocks can crown.</Td>
            </tr>
            <tr>
              <Td>Rebase</Td>
              <Td>Repeating the comparison against a new champion. Your place and your fee are kept.</Td>
            </tr>
            <tr>
              <Td>Admission key</Td>
              <Td>The finalized block and index of your payment. It fixes promotion order.</Td>
            </tr>
          </Table>
        </Card>

        <Card title="Why did my submission fail?" subtitle="Each outcome on the submission page links back to one of these.">
          <Table head={["Outcome", "What it means", "What to do"]}>
            {FAILURES.map(([code, meaning, action]) => (
              <tr key={code}>
                <Td className="font-medium">{code}</Td>
                <Td className="text-muted">{meaning}</Td>
                <Td className="text-muted">{action}</Td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title="Local development" subtitle="Run the whole stack on one machine.">
          <pre className="overflow-x-auto rounded-[var(--radius-sm)] border border-line bg-surface-2 p-3 font-mono text-[12px] leading-relaxed text-muted">
{`make setup      # install Python and web dependencies
make db         # start PostgreSQL and apply migrations
make seed       # labelled demo dataset
make dev        # API, controller, two workers and the web app
make test-all   # unit and database-backed tests
make reset      # wipe and reseed the demo data`}
          </pre>
          <p className="mt-3 text-[13px] leading-relaxed text-muted">
            The repository holds the corrected protocol specification, the requirements and acceptance matrix,
            architecture decisions, the threat model, the integration-readiness checklist and the runbooks for
            deployment, backup, recovery, refunds, rollback and incidents.
          </p>
        </Card>

        <Card title="Supported software package" subtitle="What a customer would receive. Not sold in this build.">
          <p className="text-[13px] leading-relaxed text-muted">
            Approved champions are merged into an open reference stack and released on a quarterly cadence after
            a soak test, as a validated build for one profile with a capacity test on the customer&apos;s own
            hardware. RamCove does not route production requests to miners and offers no inference API. There is no
            customer billing portal in this build, and no customer, revenue or partnership exists.
          </p>
        </Card>
      </div>
    </div>
  );
}
