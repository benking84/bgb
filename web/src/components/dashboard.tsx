"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatBytes, formatWhen, statusLabel } from "@/lib/format";
import type { Health, Job, Summary } from "@/lib/types";

export function Dashboard() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [seeding, setSeeding] = useState(false);

  async function load() {
    try {
      const [nextJobs, nextSummary, nextHealth] = await Promise.all([
        api<Job[]>("/api/jobs"),
        api<Summary>("/api/summary"),
        api<Health>("/api/health"),
      ]);
      setJobs(nextJobs);
      setSummary(nextSummary);
      setHealth(nextHealth);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load jobs");
    }
  }

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      if (!stopped) await load();
    };
    void tick();
    const timer = setInterval(tick, 4000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, []);

  async function seed() {
    setSeeding(true);
    setError("");
    try {
      await api("/api/demo/seed", { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the sample");
    } finally {
      setSeeding(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-heading text-4xl tracking-tight">Backup jobs</h1>
          <p className="mt-2 max-w-xl text-muted-foreground">
            Each job is a Workspace selection — mail, Drive, and the people who own them —
            written as compressed, deduplicated volumes.
          </p>
        </div>
        <Button nativeButton={false} render={<Link href="/jobs/new" />}>New backup</Button>
      </header>

      {error && (
        <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      <section className="grid gap-3 sm:grid-cols-3">
        <Stat label="Stored blocks" value={summary ? formatBytes(summary.stored_bytes) : "…"} detail={summary ? `${summary.blocks} unique blocks` : " "} />
        <Stat label="Volumes" value={summary ? String(summary.volumes) : "…"} detail="dblock objects" />
        <Stat label="Last good run" value={summary ? formatWhen(summary.last_success) : "…"} detail={health ? `${health.index} · ${health.volumes}` : " "} />
      </section>

      {jobs === null && !error && <p className="text-sm text-muted-foreground">Loading jobs…</p>}

      {jobs && jobs.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Nothing is being backed up yet</CardTitle>
            <CardDescription>
              Load the Northwind sample to see dedup against fixture mail and Drive, or create a job
              that talks to a real Workspace domain.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Button onClick={seed} disabled={seeding}>
              {seeding ? "Loading sample…" : "Load the Northwind sample"}
            </Button>
            <Button variant="outline" nativeButton={false} render={<Link href="/jobs/new" />}>
              Create a real job
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3">
        {jobs?.map((job) => (
          <Link key={job.id} href={`/jobs/view?id=${job.id}`} className="block">
            <Card className="transition-colors hover:bg-accent/40">
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-lg">{job.name}</CardTitle>
                    <CardDescription className="mt-1">
                      {job.description || job.retention_description}
                    </CardDescription>
                  </div>
                  <Badge variant={job.latest_run?.status === "failed" ? "destructive" : "secondary"}>
                    {statusLabel(job.latest_run?.status)}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>{job.sources.join(", ")}</span>
                <span>{job.all_users ? "all users" : `${job.users.length} users`}</span>
                <span>{job.fileset_count} versions</span>
                <span>{job.demo ? "sample data" : job.schedule || "manual"}</span>
                <span>last activity {formatWhen(job.latest_run?.started_at)}</span>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="font-heading text-2xl">{value}</CardTitle>
        <p className="text-xs text-muted-foreground">{detail}</p>
      </CardHeader>
    </Card>
  );
}
