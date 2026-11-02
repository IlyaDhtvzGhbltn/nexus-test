export type PermissionType = 'CREATE' | 'READ' | 'UPDATE' | 'DELETE' | 'LIST' | 'ADMIN';

export const ALL_PERMISSIONS: PermissionType[] = [
  'CREATE',
  'READ',
  'UPDATE',
  'DELETE',
  'LIST',
  'ADMIN',
];

export interface Role {
  id: number;
  name: string;
  permissions: PermissionType[];
}

export interface User {
  id: number;
  login: string;
  is_active: boolean;
  is_superadmin: boolean;
  created_at: string;
}

export type RepoType = 'hosted' | 'proxy';

export interface Repository {
  id: number;
  name: string;
  type: RepoType;
  upstream_url: string | null;
  allow_overwrite: boolean;
  created_at: string;
}

export interface AccessGrant {
  id: number;
  user: { id: number; login: string };
  role: Role;
}

export type QuarantineStatus = 'UNKNOWN' | 'CLEAN' | 'QUARANTINED' | 'WHITELISTED';

export interface ScanFinding {
  id: string;
  package: string;
  installed: string;
  severity: string;
  title: string;
}

export interface SecurityVersion {
  id: number;
  repository_name: string;
  package_name: string;
  version: string;
  quarantine_status: QuarantineStatus;
  size: number;
  created_at: string;
  last_scanned_at: string | null;
  scan_findings: ScanFinding[];
}

export interface WhitelistRule {
  id: number;
  package_name: string;
  version: string;
  reason: string;
  created_by_login: string;
  created_at: string;
}

export interface DownloadLog {
  id: string;
  user_login: string;
  repository_name: string;
  package_name: string;
  package_version: string;
  downloaded_at: string;
  user_agent: string | null;
}

export interface OperatorLog {
  id: string;
  actor_login: string;
  action: string;
  target: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface PackageVersion {
  id: number;
  version: string;
  description: string | null;
  dependencies: Record<string, string>;
  size: number;
  shasum: string | null;
  quarantine_status: QuarantineStatus;
  created_at: string;
}

export interface Package {
  id: number;
  name: string;
  dist_tags: Record<string, string>;
  versions: PackageVersion[];
}
