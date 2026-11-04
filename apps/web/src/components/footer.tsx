import { Wordmark } from "@/components/shell";
import { REPO_URL, WHITEPAPER_PDF } from "@/lib/site";
import Link from "next/link";

const COLUMNS: {
  title: string;
  links: { href: string; label: string; external?: boolean }[];
}[] = [
  {
    title: "Compete",
    links: [
      { href: "/dashboard", label: "Miner dashboard" },
      { href: "/docs#miners", label: "Mining guide" },
      { href: "/docs/rules", label: "Competition rules" },
    ],
  },
  {
    title: "Validate",
    links: [
      { href: "/docs#validators", label: "Validator guide" },
      { href: "/status", label: "Service status" },
    ],
  },
  {
    title: "Learn",
    links: [
      { href: "/docs", label: "Documentation" },
      { href: WHITEPAPER_PDF, label: "Whitepaper", external: true },
      { href: REPO_URL, label: "Source on GitHub", external: true },
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
            A Bittensor subnet that pays for verified software changes which let
            the same GPU serve more useful AI requests, across open models and
            GPU types.
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
                      <Link
                        href={l.href}
                        className="text-[14px] text-muted transition-colors hover:text-text"
                      >
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
          This site shows the RamCove subnet running in simulation mode: the
          chain, the beacon and the GPU workers are simulated, and every number
          they produce is labelled.
        </p>
      </div>
    </footer>
  );
}
