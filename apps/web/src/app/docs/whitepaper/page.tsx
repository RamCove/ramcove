import { DocsTabs } from "@/components/docs-tabs";
import { PageHeader } from "@/components/ui";
import { WHITEPAPER_PDF } from "@/lib/site";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Whitepaper" };

const SECTIONS = [
  "Abstract and executive explanation",
  "The problem and why now",
  "Product and first customer",
  "Technical approach, profile and hardware",
  "Network architecture, submission lifecycle and queue",
  "Evaluation: what is measured and how",
  "Champion rule and incentives",
  "Security, auditability and trust assumptions",
  "Why RamCove is built this way",
  "Commercial model and financial sustainability",
  "Why Bittensor, token mechanics and governance",
  "Milestones, evidence gates, risks and reasons to stop",
];

const APPENDICES = [
  "Profile, quote, receipt and report formats",
  "Workload, statistics, parameters, queue and costs",
  "Pseudocode",
  "Claim and evidence ledger",
  "Open decisions, in priority order",
  "Glossary",
];

export default function WhitepaperPage() {
  return (
    <div className="min-w-0 space-y-8">
      <DocsTabs active="whitepaper" />
      <PageHeader
        eyebrow="Whitepaper · v0.2 · 2026.7.27"
        title="The RamCove whitepaper"
        lede="The full design in 29 pages: the problem, how serving capacity is measured, how a crown changes hands, incentives, security, the commercial model and the roadmap."
        actions={
          <>
            <a
              href={WHITEPAPER_PDF}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-10 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-4 text-[14px] font-medium text-on-accent transition-colors hover:bg-accent-strong"
            >
              Open PDF <span aria-hidden>↗</span>
            </a>
            <a
              href={WHITEPAPER_PDF}
              download
              className="inline-flex h-10 items-center rounded-[var(--radius-sm)] border border-line-strong bg-surface px-4 text-[14px] font-medium text-text transition-colors hover:bg-surface-2"
            >
              Download
            </a>
          </>
        }
      />

      <div className="grid items-start gap-5 lg:grid-cols-[1fr_2.2fr]">
        <nav
          aria-label="Contents"
          className="rounded-[var(--radius-card)] border border-line bg-surface p-6 lg:sticky lg:top-24"
          style={{ boxShadow: "var(--shadow)" }}
        >
          <p className="eyebrow">Contents</p>
          <ol className="mt-4 space-y-2">
            {SECTIONS.map((s, i) => (
              <li key={s} className="flex gap-3 text-[14px] leading-snug">
                <span className="num w-6 shrink-0 font-mono text-[12px] text-accent-ink">{String(i + 2).padStart(2, "0")}</span>
                <span className="text-text">{s}</span>
              </li>
            ))}
          </ol>
          <p className="eyebrow mt-6">Appendices</p>
          <ol className="mt-3 space-y-2">
            {APPENDICES.map((s, i) => (
              <li key={s} className="flex gap-3 text-[13.5px] leading-snug">
                <span className="w-5 shrink-0 font-mono text-[12px] text-faint">{String.fromCharCode(65 + i)}</span>
                <span className="text-muted">{s}</span>
              </li>
            ))}
          </ol>
        </nav>

        <div className="min-w-0">
          <div
            className="hidden overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface md:block"
            style={{ boxShadow: "var(--shadow-lift)" }}
          >
            <iframe
              src={`${WHITEPAPER_PDF}#view=FitH`}
              title="RamCove whitepaper"
              className="block h-[82vh] w-full"
            />
          </div>
          <div className="rounded-[var(--radius-card)] border border-line bg-surface p-6 md:hidden">
            <p className="text-[15px] leading-relaxed text-muted">
              Phones show PDFs best on their own. Open the whitepaper to read it full screen.
            </p>
            <a
              href={WHITEPAPER_PDF}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-flex h-11 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-5 text-[14px] font-medium text-on-accent"
            >
              Open the whitepaper <span aria-hidden>↗</span>
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
