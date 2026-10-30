"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, downloadContent } from "@/lib/api";
import { formatBytes, formatWhen, statusLabel } from "@/lib/format";
import type { FileEntry, FileSet, Job, Run } from "@/lib/types";

export function JobView() {
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("id") ?? "";
  const [job, setJob] = useState<Job | null>(null);
  const [filesets, setFilesets] = useState<FileSet[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [filesetId, setFilesetId] = useState("");
  const [prefix, setPrefix] = useState("");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [nextJob, nextSets, nextRuns] = await Promise.all([
        api<Job>(`/api/jobs/${id}`),
        api<FileSet[]>(`/api/jobs/${id}/filesets`),
        api<Run[]>(`/api/jobs/${id}/runs`),
      ]);
      setJob(nextJob);
      setFilesets(nextSets);
      setRuns(nextRuns);
      setFilesetId((current) => current || nextSets[0]?.id || "");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this job");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const status = job?.latest_run?.status;
    if (status !== "running" && status !== "queued") return;
    const timer = setInterval(() => void load(), 1500);
    return () => clearInterval(timer);
  }, [job?.latest_run?.status, load]);

  useEffect(() => {
    if (!id || !filesetId) {
      setFiles([]);
      return;
    }
    const query = new URLSearchParams({ prefix, limit: "300" });
    api<{ files: FileEntry[] }>(`/api/jobs/${id}/filesets/${filesetId}/files?${query}`)
      .then((body) => setFiles(body.files))
      .catch((err: Error) => setError(err.message));
  }, [id, filesetId, prefix]);

  async function runBackup() {
    if (!job) return;
    setBusy("run");
    setError("");
    try {
      await api(`/api/jobs/${job.id}/run?wait=${job.demo ? "true" : "false"}`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backup failed");
    } finally {
      setBusy("");
    }
  }

  async function verify() {
    if (!job) return;
    setBusy("verify");
    setError("");
    try {
      const report = await api<{ ok: boolean; issues: string[]; extra: string[] }>(
        `/api/jobs/${job.id}/verify?full=true`,
        { method: "POST" },
      );
      if (!report.ok) {
        setError(report.issues.join("; ") || "Verification failed");
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setBusy("");
    }
  }

  async function remove() {
    if (!job) return;
    setBusy("delete");
    try {
      await api(`/api/jobs/${job.id}`, { method: "DELETE" });
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the job");
      setBusy("");
    }
  }

  if (!id) {
    return <p className="text-sm text-muted-foreground">Pick a job from the list.</p>;
  }
  if (!job && !error) {
    return <p className="text-sm text-muted-foreground">Loading the job…</p>;
  }
  if (!job) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  const stats = (job.latest_run?.stats ?? {}) as Record<string, number | string | undefined>;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs tracking-[0.14em] text-muted-foreground uppercase">
            <Link href="/" className="hover:text-foreground">
              Jobs
            </Link>
          </p>
          <h1 className="font-heading text-4xl tracking-tight">{job.name}</h1>
          <p className="mt-2 max-w-2xl text-muted-foreground">
            {job.description || job.retention_description}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={runBackup} disabled={busy !== ""}>
            {busy === "run" ? "Running…" : "Run backup"}
          </Button>
          <Button variant="outline" onClick={verify} disabled={busy !== "" || filesets.length === 0}>
            {busy === "verify" ? "Checking…" : "Verify"}
          </Button>
          <Button variant="destructive" onClick={() => setConfirmDelete(true)} disabled={busy !== ""}>
            Delete
          </Button>
        </div>
      </header>

      {error && (
        <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

      <section className="grid gap-3 sm:grid-cols-4">
        <Metric label="Status" value={statusLabel(job.latest_run?.status)} />
        <Metric label="Phase" value={job.latest_run?.phase || "—"} />
        <Metric label="New blocks" value={String(stats.blocks_new ?? "—")} />
        <Metric label="Reused blocks" value={String(stats.blocks_reused ?? "—")} />
      </section>

      <Tabs defaultValue="catalog">
        <TabsList>
          <TabsTrigger value="catalog">Catalog</TabsTrigger>
          <TabsTrigger value="versions">Versions</TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
        </TabsList>
        <TabsContent value="catalog" className="mt-4 flex flex-col gap-3">
          {filesets.length === 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>No version yet</CardTitle>
                <CardDescription>
                  Run the backup. The first pass reads every object. Later passes reuse blocks whose
                  hash is already stored.
                </CardDescription>
              </CardHeader>
            </Card>
          ) : (
            <>
              <div className="flex flex-col gap-2 sm:flex-row">
                <select
                  className="h-9 rounded-lg border border-input bg-transparent px-2.5 text-sm"
                  value={filesetId}
                  onChange={(event) => setFilesetId(event.target.value)}
                >
                  {filesets.map((fileset) => (
                    <option key={fileset.id} value={fileset.id}>
                      {formatWhen(fileset.created_at)} · {fileset.file_count} files · {formatBytes(fileset.bytes)}
                    </option>
                  ))}
                </select>
                <Input
                  value={prefix}
                  onChange={(event) => setPrefix(event.target.value)}
                  placeholder="Filter by path, for example gmail/ or drive/shared/"
                />
              </div>
              {files.length === 0 ? (
                <p className="text-sm text-muted-foreground">No files match that prefix.</p>
              ) : (
                <div className="overflow-hidden rounded-xl ring-1 ring-foreground/10">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted/60 text-xs tracking-wide text-muted-foreground uppercase">
                      <tr>
                        <th className="px-3 py-2 font-medium">Path</th>
                        <th className="px-3 py-2 font-medium">Size</th>
                        <th className="px-3 py-2 font-medium" />
                      </tr>
                    </thead>
                    <tbody>
                      {files.map((file) => (
                        <tr key={file.source_id} className="border-t border-border">
                          <td className="px-3 py-2 font-mono text-xs break-all">{file.path}</td>
                          <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">
                            {formatBytes(file.size)}
                          </td>
                          <td className="px-3 py-2 text-right">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() =>
                                downloadContent(
                                  `/api/jobs/${job.id}/filesets/${filesetId}/content?path=${encodeURIComponent(file.path)}`,
                                  file.path.split("/").pop() || "file",
                                ).catch((err: Error) => setError(err.message))
                              }
                            >
                              Restore
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </TabsContent>
        <TabsContent value="versions" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Versions</CardTitle>
              <CardDescription>{job.retention_description}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {filesets.length === 0 && <p className="text-sm text-muted-foreground">No versions yet.</p>}
              {filesets.map((fileset) => (
                <div key={fileset.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span>{formatWhen(fileset.created_at)}</span>
                  <span className="text-muted-foreground">
                    {fileset.file_count} files · {formatBytes(fileset.bytes)}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="activity" className="mt-4 flex flex-col gap-3">
          {runs.length === 0 && <p className="text-sm text-muted-foreground">No runs yet.</p>}
          {runs.map((run) => (
            <Card key={run.id} size="sm">
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="text-base">
                    {formatWhen(run.started_at)} · {run.phase}
                  </CardTitle>
                  <Badge variant={run.status === "failed" ? "destructive" : "secondary"}>
                    {statusLabel(run.status)}
                  </Badge>
                </div>
                {run.error && <CardDescription className="text-destructive">{run.error}</CardDescription>}
              </CardHeader>
              <CardContent className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                <span>Files in snapshot: {String(run.stats.files ?? "—")}</span>
                <span>Read this run: {String(run.stats.files_read ?? "—")}</span>
                <span>Unchanged: {String(run.stats.files_unchanged ?? "—")}</span>
                <span>Removed from snapshot: {String(run.stats.files_deleted ?? "—")}</span>
                <span>New blocks: {String(run.stats.blocks_new ?? "—")}</span>
                <span>Reused blocks: {String(run.stats.blocks_reused ?? "—")}</span>
                <span>Logical bytes: {formatBytes(Number(run.stats.bytes ?? 0))}</span>
                <span>Uploaded ciphertext: {formatBytes(Number(run.stats.stored_bytes ?? 0))}</span>
              </CardContent>
            </Card>
          ))}
        </TabsContent>
      </Tabs>

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {job.name}?</DialogTitle>
            <DialogDescription>
              This removes the job, the index, and the encrypted volumes for this job. It does not
              touch the live Workspace data.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>
              Keep it
            </Button>
            <Button variant="destructive" onClick={remove} disabled={busy === "delete"}>
              {busy === "delete" ? "Deleting…" : "Delete job and volumes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-lg capitalize">{value}</CardTitle>
      </CardHeader>
    </Card>
  );
}
