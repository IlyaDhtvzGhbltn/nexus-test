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

export interface PackageVersion {
  id: number;
  version: string;
  description: string | null;
  dependencies: Record<string, string>;
  size: number;
  shasum: string | null;
  created_at: string;
}

export interface Package {
  id: number;
  name: string;
  dist_tags: Record<string, string>;
  versions: PackageVersion[];
}
