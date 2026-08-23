export interface Role {
  id: number;
  name: string;
}

export interface User {
  id: number;
  login: string;
  is_active: boolean;
  created_at: string;
  roles: Role[];
}

export type RepoType = 'hosted' | 'proxy';
export type AccessType = 'READ' | 'WRITE';

export interface Repository {
  id: number;
  name: string;
  type: RepoType;
  upstream_url: string | null;
  created_at: string;
}

export interface Permission {
  id: number;
  role: Role;
  access_type: AccessType;
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
