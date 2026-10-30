export type Run = {
  id: string;
  job_id: string;
  status: string;
  phase: string;
  started_at: string;
  finished_at?: string | null;
  error?: string | null;
  stats: Record<string, unknown>;
};

export type FileSet = {
  id: string;
  job_id: string;
  created_at: string;
  volume_id: string;
  file_count: number;
  bytes: number;
};

export type Job = {
  id: string;
  name: string;
  description: string;
  users: string[];
  all_users: boolean;
  sources: string[];
  include_shared_drives: boolean;
  retention: string;
  retention_description?: string;
  schedule: string;
  enabled: boolean;
  demo: boolean;
  block_size: number | null;
  volume_size: number | null;
  created_at: string;
  updated_at: string;
  latest_run: Run | null;
  latest_fileset: FileSet | null;
  fileset_count: number;
};

export type FileEntry = {
  path: string;
  source_id: string;
  scope: string;
  size: number;
  mtime: string | null;
  revision: string;
  metadata: Record<string, unknown>;
};

export type Settings = {
  workspace_domain: string;
  admin_email: string;
  auth_mode: string;
  service_account_secret: string;
  service_account_email: string;
  oauth_secret: string;
  encryption_key_secret: string;
  gcs_bucket: string;
  gcs_prefix: string;
  block_size: number;
  volume_size: number;
  verify_samples: number;
  compact_waste_threshold: number;
};

export type SourceInfo = {
  name: string;
  title: string;
  supported: boolean;
  scopes: string[];
  description: string;
};

export type Summary = {
  jobs: number;
  stored_bytes: number;
  volumes: number;
  blocks: number;
  last_success: string | null;
};

export type Health = {
  ok: boolean;
  version: string;
  index: string;
  volumes: string;
  gcp: string;
};
