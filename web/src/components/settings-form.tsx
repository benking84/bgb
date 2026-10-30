"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { Health, Settings, SourceInfo } from "@/lib/types";

export function SettingsForm() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [directoryScope, setDirectoryScope] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setToken(localStorage.getItem("bgb.token") ?? "");
    Promise.all([
      api<Settings>("/api/settings"),
      api<{ sources: SourceInfo[]; directory_scope: string }>("/api/sources"),
      api<Health>("/api/health"),
    ])
      .then(([nextSettings, catalog, nextHealth]) => {
        setSettings(nextSettings);
        setSources(catalog.sources);
        setDirectoryScope(catalog.directory_scope);
        setHealth(nextHealth);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setSettings((current) => (current ? { ...current, [key]: value } : current));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const saved = await api<Settings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(settings),
      });
      setSettings(saved);
      if (token) localStorage.setItem("bgb.token", token);
      else localStorage.removeItem("bgb.token");
      setMessage("Settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save settings");
    } finally {
      setSaving(false);
    }
  }

  async function testConnection() {
    setError("");
    setMessage("");
    try {
      const result = await api<{ ok: boolean; mode: string; detail: string }>("/api/connection-test", {
        method: "POST",
      });
      setMessage(`${result.mode}: ${result.detail}`);
      if (!result.ok) setError(result.detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection test failed");
    }
  }

  if (!settings && !error) {
    return <p className="text-sm text-muted-foreground">Loading settings…</p>;
  }
  if (!settings) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  return (
    <form onSubmit={save} className="mx-auto flex max-w-2xl flex-col gap-5">
      <header>
        <h1 className="font-heading text-4xl tracking-tight">Settings</h1>
        <p className="mt-2 text-muted-foreground">
          Index {health?.index ?? "…"}, volumes {health?.volumes ?? "…"}. Credentials stay in Secret
          Manager. This page only stores their names.
        </p>
      </header>
      {error && (
        <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      {message && !error && (
        <p className="rounded-lg border border-border bg-card px-3 py-2 text-sm">{message}</p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Workspace</CardTitle>
          <CardDescription>
            Domain-wide delegation uses a service account. OAuth is for one consented user, without
            the Directory API.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <Field label="Domain">
            <Input value={settings.workspace_domain} onChange={(event) => update("workspace_domain", event.target.value)} placeholder="school.edu" />
          </Field>
          <Field label="Admin email">
            <Input value={settings.admin_email} onChange={(event) => update("admin_email", event.target.value)} placeholder="admin@school.edu" />
          </Field>
          <Field label="Auth mode">
            <select
              className="h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
              value={settings.auth_mode}
              onChange={(event) => update("auth_mode", event.target.value)}
            >
              <option value="service_account">Service account, domain-wide delegation</option>
              <option value="oauth">OAuth refresh token, one user</option>
            </select>
          </Field>
          <Field label="Service account secret name">
            <Input value={settings.service_account_secret} onChange={(event) => update("service_account_secret", event.target.value)} />
          </Field>
          <Field label="Service account email (keyless signing)">
            <Input value={settings.service_account_email} onChange={(event) => update("service_account_email", event.target.value)} placeholder="bgb-run@project.iam.gserviceaccount.com" />
          </Field>
          <Field label="OAuth secret name">
            <Input value={settings.oauth_secret} onChange={(event) => update("oauth_secret", event.target.value)} />
          </Field>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Storage</CardTitle>
          <CardDescription>Volumes are encrypted before they are written. The key secret must be 32 bytes, or 64 hex characters.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <Field label="Cloud Storage bucket">
            <Input value={settings.gcs_bucket} onChange={(event) => update("gcs_bucket", event.target.value)} />
          </Field>
          <Field label="Object prefix">
            <Input value={settings.gcs_prefix} onChange={(event) => update("gcs_prefix", event.target.value)} />
          </Field>
          <Field label="Encryption key secret">
            <Input value={settings.encryption_key_secret} onChange={(event) => update("encryption_key_secret", event.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Block size (bytes)">
              <Input type="number" value={settings.block_size} onChange={(event) => update("block_size", Number(event.target.value))} />
            </Field>
            <Field label="Volume size (bytes)">
              <Input type="number" value={settings.volume_size} onChange={(event) => update("volume_size", Number(event.target.value))} />
            </Field>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Scopes to authorize</CardTitle>
          <CardDescription>
            In the Admin console, add the service account client id under Security → Access and data
            control → API controls → Domain-wide delegation, with these scopes.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          {sources.map((source) => (
            <div key={source.name}>
              <p className="font-medium">{source.title}</p>
              {source.scopes.length === 0 ? (
                <p className="text-muted-foreground">No scope. {source.description}</p>
              ) : (
                source.scopes.map((scope) => (
                  <p key={scope} className="font-mono text-xs break-all text-muted-foreground">
                    {scope}
                  </p>
                ))
              )}
            </div>
          ))}
          <div>
            <p className="font-medium">Directory (list every user)</p>
            <p className="font-mono text-xs break-all text-muted-foreground">{directoryScope}</p>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>API token</CardTitle>
          <CardDescription>
            Optional. If the server was started with BGB_API_TOKEN, paste it here. It stays in this
            browser. Cloud Run IAM is the real gate in production.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Leave empty on a local demo" />
        </CardContent>
      </Card>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save settings"}
        </Button>
        <Button type="button" variant="outline" onClick={testConnection}>
          Test Workspace connection
        </Button>
      </div>
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
