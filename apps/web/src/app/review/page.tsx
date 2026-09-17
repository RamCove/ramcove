import { Card, Empty } from "@/components/ui";
import { apiGetOrNull } from "@/lib/api";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ReviewPanel } from "./review-panel";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Review" };

type Queue = {
  criteria: { id: string; title: string }[];
  items: {
    review_id: string;
    submission_id: string;
    author: string;
    lineage: string;
    bound_gain_ppm: number | null;
    triage_gain_ppm: number | null;
    opened_at: string;
    due_at: string;
    is_own_submission: boolean;
  }[];
};

type Appeals = {
  items: {
    id: string;
    submission_id: string;
    kind: string;
    grounds: string;
    appellant: string;
    disputed_decider: string | null;
    due_at: string;
    may_decide: boolean;
  }[];
};

export default async function ReviewPage() {
  const cookie = (await cookies()).toString();
  const [queue, appeals] = await Promise.all([
    apiGetOrNull<Queue>("/v1/review/queue", cookie),
    apiGetOrNull<Appeals>("/v1/appeals", cookie),
  ]);
  if (!queue) {
    return (
      <Card title="Review">
        <Empty title="Sign in as a reviewer">
          Promotion review needs the reviewer role. Authors can never review their own submission.
        </Empty>
      </Card>
    );
  }
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-[22px] font-semibold tracking-tight">Promotion review</h1>
        <p className="mt-1 max-w-3xl text-[14px] leading-relaxed text-muted">
          Every promotion passes review against published criteria. A rejection must cite a failed criterion and
          explain the evidence. Declare a conflict instead of deciding if you are involved with the author.
        </p>
      </header>
      <ReviewPanel queue={queue} appeals={appeals?.items ?? []} />
    </div>
  );
}
