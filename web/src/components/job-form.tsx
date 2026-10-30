"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { SourceInfo } from "@/lib/types";

const RETENTION = [
  { value: "policy:1W:1D,4W:1W,12M:1M", label: "Smart — daily, weekly, then monthly" },
  { value: "time:30D", label: "Keep 30 days" },
  { value: "versions:7", label: "Keep 7 versions" },
  { value: "", label: "Keep every version" },
];

export function JobForm() {
  const router = useRouter();
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [name, setName] = useState("Campus mail and drive");
  const [description, setDescription] = useState("");
  const [users, setUsers] = useState("");
  const [allUsers, setAllUsers] = useState(false);
  const [selected, setSelected] = useState<string[]>(["gmail", "drive"]);
  const [shared, setShared] = useState(true);
  const [retention, setRetention] = useState(RETENTION[0].value);
  const [schedule, setSchedule] = useState("0 2 * * *");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ sources: SourceInfo[] }>("/api/sources")
      .then((body) => setSources(body.sources))
      .catch((err: Error) => setError(err.message));
  }, []);

  function toggle(name: string) {
    setSelected((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    );
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const job = await api<{ id: string }>("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          name,
          description,
          users: users
            .split(/[\s,]+/)
            .map((item) => item.trim())
            .filter(Boolean),
          all_users: allUsers,
          sources: selected,
          include_shared_drives: shared,
          retention,
          schedule,
          enabled: true,
          demo: false,
        }),
      });
      router.push(`/jobs/view?id=${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the job");
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto flex max-w-2xl flex-col gap-5">
      <header>
        <h1 className="font-heading text-4xl tracking-tight">New backup</h1>
        <p className="mt-2 text-muted-foreground">
          A job impersonates each person with domain-wide delegation, or a single consented user
          in OAuth mode. Shared drives are read once, not once per member.
        </p>
      </header>
      {error && (
        <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>What to copy</CardTitle>
          <CardDescription>Gmail and Drive are the paths that are fully exercised. Contacts is included. Keep is not available.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Field label="Name">
            <Input value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label="Notes">
            <Textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Faculty inboxes and the commons drive" />
          </Field>
          <div className="grid gap-3">
            {sources.map((source) => (
              <label key={source.name} className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-1 accent-[var(--primary)]"
                  checked={selected.includes(source.name)}
                  disabled={!source.supported}
                  onChange={() => toggle(source.name)}
                />
                <span>
                  <span className="font-medium">{source.title}</span>
                  {!source.supported && <span className="ml-2 text-muted-foreground">no API</span>}
                  <span className="mt-0.5 block text-muted-foreground">{source.description}</span>
                </span>
              </label>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-[var(--primary)]" checked={shared} onChange={(event) => setShared(event.target.checked)} />
            Include shared drives, once, as the admin user
          </label>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Who</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Field label="Users">
            <Textarea
              value={users}
              onChange={(event) => setUsers(event.target.value)}
              placeholder="ada@school.edu, grace@school.edu"
              disabled={allUsers}
            />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-[var(--primary)]" checked={allUsers} onChange={(event) => setAllUsers(event.target.checked)} />
            Every non-suspended user in the domain (Directory API)
          </label>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Retention and schedule</CardTitle>
          <CardDescription>The newest version is always kept. The schedule is a UTC cron expression, fired by Cloud Scheduler.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Field label="Retention">
            <select
              className="h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
              value={retention}
              onChange={(event) => setRetention(event.target.value)}
            >
              {RETENTION.map((option) => (
                <option key={option.label} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Cron, UTC">
            <Input value={schedule} onChange={(event) => setSchedule(event.target.value)} placeholder="0 2 * * *" />
          </Field>
        </CardContent>
      </Card>
      <Button type="submit" size="lg" disabled={saving}>
        {saving ? "Saving…" : "Create job"}
      </Button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
