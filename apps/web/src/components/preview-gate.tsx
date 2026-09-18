import Link from "next/link";

/** Shown on pages that need a signed-in role when the site is the read-only public preview. */
export function PreviewGate({ what }: { what: string }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface px-6 py-14 text-center sm:px-10">
      <p className="eyebrow">Read-only preview</p>
      <h2 className="font-display text-balance mx-auto mt-4 max-w-xl text-[30px] leading-[1.1] text-text sm:text-[36px]">
        {what} needs a signed-in role
      </h2>
      <p className="mx-auto mt-4 max-w-lg text-[15px] leading-relaxed text-muted">
        This public preview shows a snapshot of the local simulation and has no API behind it, so sign-in,
        submitting and every change are switched off. Run RamCove locally to use this page with the demo
        identities.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <a
          href="https://github.com/RooM-Labs/room#run-it-locally"
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-11 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-5 text-[14px] font-medium text-on-accent transition-colors hover:bg-accent-strong"
        >
          How to run it locally <span aria-hidden>↗</span>
        </a>
        <Link
          href="/"
          className="inline-flex h-11 items-center rounded-[var(--radius-sm)] border border-line-strong bg-bg px-5 text-[14px] font-medium text-text transition-colors hover:bg-surface-2"
        >
          Back to the overview
        </Link>
      </div>
    </div>
  );
}
