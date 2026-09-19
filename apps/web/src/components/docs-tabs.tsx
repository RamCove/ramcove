import { WHITEPAPER_PDF } from "@/lib/site";
import clsx from "clsx";
import Link from "next/link";

const TABS = [
  { href: "/docs", key: "guide", label: "How it works" },
  { href: "/docs/rules", key: "rules", label: "Rules" },
] as const;

/** The guide and the live competition rules, plus the whitepaper, which opens full screen as a PDF. */
export function DocsTabs({ active }: { active: (typeof TABS)[number]["key"] }) {
  return (
    <nav aria-label="Documentation" className="inline-flex gap-1 rounded-full border border-line bg-surface p-1">
      {TABS.map((t) => (
        <Link
          key={t.key}
          href={t.href}
          aria-current={t.key === active ? "page" : undefined}
          className={clsx(
            "rounded-full px-4 py-1.5 text-[14px] transition-colors",
            t.key === active ? "bg-ink font-medium text-on-ink" : "text-muted hover:bg-surface-2 hover:text-text",
          )}
        >
          {t.label}
        </Link>
      ))}
      <a
        href={WHITEPAPER_PDF}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-[14px] text-muted transition-colors hover:bg-surface-2 hover:text-text"
      >
        Whitepaper <span aria-hidden className="text-faint">↗</span>
      </a>
    </nav>
  );
}
