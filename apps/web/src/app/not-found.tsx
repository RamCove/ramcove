import Link from "next/link";

export default function NotFound() {
  return (
    <div className="py-16 text-center sm:py-24">
      <p className="eyebrow">404 · not found</p>
      <h1 className="font-display text-balance mx-auto mt-5 max-w-2xl text-[44px] leading-[1.05] sm:text-[60px]">
        That page does not exist
      </h1>
      <p className="mx-auto mt-5 max-w-md text-[16px] leading-relaxed text-muted">
        The link may be out of date. The overview shows the current champion, the queue and the service status.
      </p>
      <Link
        href="/"
        className="mt-8 inline-flex h-11 items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-5 text-[14px] font-medium text-on-accent transition-colors hover:bg-accent-strong"
      >
        Back to the overview <span aria-hidden>→</span>
      </Link>
    </div>
  );
}
