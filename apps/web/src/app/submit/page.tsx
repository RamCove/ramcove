import { Notice, PageHeader } from "@/components/ui";
import { apiGetOrNull } from "@/lib/api";
import type { Metadata } from "next";
import { SubmitFlow } from "./submit-flow";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Submit" };

type Overview = {
  capacity: { accepting_paid_submissions: boolean; reason: string };
  champion: { version: number };
};
type Meta = { demo_features: boolean };
type Fixtures = { fixtures: { name: string; title: string; mechanism: string; method: string }[] };

export default async function SubmitPage() {
  const [overview, meta, fixtures] = await Promise.all([
    apiGetOrNull<Overview>("/v1/overview"),
    apiGetOrNull<Meta>("/v1/meta"),
    apiGetOrNull<Fixtures>("/v1/demo/fixtures"),
  ]);
  return (
    <div className="min-w-0 space-y-8">
      <PageHeader
        eyebrow="For miners"
        title="Start a submission"
        lede="Six steps: see the requirements, prepare and sign your artifact, run the free checks, reserve capacity, review the quote and pay, then follow the work. You are only asked to pay once a slot is reserved for you."
      />
      {overview && !overview.capacity.accepting_paid_submissions && (
        <Notice tone="warn" title="Paid admissions are closed right now">
          {overview.capacity.reason} The free checks and the waiting list still work.
        </Notice>
      )}
      <SubmitFlow
        capacityOpen={overview?.capacity.accepting_paid_submissions ?? false}
        capacityReason={overview?.capacity.reason ?? "Capacity is unknown while the API is unreachable."}
        fixtures={fixtures?.fixtures ?? []}
        demo={meta?.demo_features ?? false}
      />
    </div>
  );
}
