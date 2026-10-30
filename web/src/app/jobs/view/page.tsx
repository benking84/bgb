import { Suspense } from "react";
import { JobView } from "@/components/job-view";

export default function JobViewPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading the job…</p>}>
      <JobView />
    </Suspense>
  );
}
