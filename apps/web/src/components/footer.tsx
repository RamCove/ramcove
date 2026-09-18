import { Wordmark } from "@/components/shell";
import Link from "next/link";

const COLUMNS: { title: string; links: { href: string; label: string; external?: boolean }[] }[] = [
  {
    title: "Compete",
    links: [
      { href: "/dashboard", label: "Miner dashboard" },
      { href: "/docs/rules", label: "Competition rules" },
      { href: "/submit", label: "Start a submission" },
    ],
  },
  {
    title: "Operate",
    links: [
      { href: "/validator", label: "Validator workspace" },
      { href: "/review", label: "Promotion review" },
      { href: "/operator", label: "Operator console" },
    ],
  },
  {
    title: "Learn",
    links: [
      { href: "/docs", label: "Documentation" },
      { href: "/status", label: "Service status" },
      { href: "https://github.com/RooM-Labs/room", label: "Source on GitHub", external: true },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-[1200px] gap-12 px-5 pb-10 pt-16 sm:px-8 lg:grid-cols-[1.3fr_2fr]">
        <div>
          <Wordmark size={24} />
          <p className="font-display mt-6 max-w-sm text-[30px] leading-[1.1] text-text">
            More AI. <span className="display-accent">Same GPU.</span>
          </p>
          <p className="mt-4 max-w-sm text-[14px] leading-relaxed text-muted">
            A proposed Bittensor subnet that pays for verified software changes which let one fixed GPU serve
            more useful AI requests.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-8 sm:grid-cols-3">
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <p className="eyebrow">{col.title}</p>
              <ul className="mt-4 space-y-2.5">
                {col.links.map((l) => (
                  <li key={l.href}>
                    {l.external ? (
                      <a
                        href={l.href}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[14px] text-muted transition-colors hover:text-text"
                      >
                        {l.label} ↗
                      </a>
                    ) : (
                      <Link href={l.href} className="text-[14px] text-muted transition-colors hover:text-text">
                        {l.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-6 sm:px-8">
        <p className="max-w-3xl text-[12.5px] leading-relaxed text-faint">
          RamCove is a proposal. Nothing here is measured on an H100, no real tokens move, and mainnet writes are
          disabled in this build.
        </p>
        <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-faint">Proposal stage · local build</p>
      </div>
    </footer>
  );
}
