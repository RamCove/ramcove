import Link from "next/link";

export default function NotFound() {
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-line px-5 py-12 text-center">
      <h1 className="text-[18px] font-semibold">That page does not exist</h1>
      <p className="mx-auto mt-2 max-w-md text-[13px] leading-relaxed text-muted">
        The link may be out of date. The overview shows the current champion, the queue and the service status.
      </p>
      <Link
        href="/"
        className="mt-4 inline-block rounded-[var(--radius-sm)] border border-accent bg-accent px-4 py-2 text-[13px] font-medium text-[#04201e]"
      >
        Back to the overview
      </Link>
    </div>
  );
}
