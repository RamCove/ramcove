import clsx from "clsx";
import Link from "next/link";

const TABS = [
  { href: "/docs", key: "guide", label: "How it works" },
  { href: "/docs/rules", key: "rules", label: "Rules" },
  { href: "/docs/whitepaper", key: "whitepaper", label: "Whitepaper" },
] as const;

/** The two parts of the documentation: the guide, and the live competition rules. */
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
    </nav>
  );
}
