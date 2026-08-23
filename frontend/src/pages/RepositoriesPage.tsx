import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import Inventory2Icon from '@mui/icons-material/Inventory2';
import SecurityIcon from '@mui/icons-material/Security';
import { api, apiErrorMessage } from '../api';
import type { AccessType, Package, Permission, Repository, RepoType, Role } from '../types';

interface CreateState {
  name: string;
  type: RepoType;
  upstreamUrl: string;
}

export default function RepositoriesPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<CreateState | null>(null);
  const [permRepo, setPermRepo] = useState<Repository | null>(null);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [newPermRole, setNewPermRole] = useState<number | ''>('');
  const [newPermAccess, setNewPermAccess] = useState<AccessType>('READ');
  const [pkgRepo, setPkgRepo] = useState<Repository | null>(null);
  const [packages, setPackages] = useState<Package[]>([]);

  const reload = () => {
    api.get<Repository[]>('/api/repositories').then((res) => setRepos(res.data)).catch((e) => setError(apiErrorMessage(e)));
    api.get<Role[]>('/api/roles').then((res) => setRoles(res.data)).catch(() => {});
  };

  useEffect(reload, []);

  const create = async () => {
    if (!creating) return;
    setError(null);
    try {
      await api.post('/api/repositories', {
        name: creating.name,
        type: creating.type,
        upstream_url: creating.type === 'proxy' ? creating.upstreamUrl : null,
      });
      setCreating(null);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const remove = async (repo: Repository) => {
    if (!window.confirm(`Delete repository "${repo.name}" and all its artifacts?`)) return;
    try {
      await api.delete(`/api/repositories/${repo.id}`);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const openPermissions = async (repo: Repository) => {
    setPermRepo(repo);
    setNewPermRole('');
    setNewPermAccess('READ');
    const { data } = await api.get<Permission[]>(`/api/repositories/${repo.id}/permissions`);
    setPermissions(data);
  };

  const addPermission = async () => {
    if (!permRepo || newPermRole === '') return;
    try {
      await api.post(`/api/repositories/${permRepo.id}/permissions`, {
        role_id: newPermRole,
        access_type: newPermAccess,
      });
      openPermissions(permRepo);
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const removePermission = async (perm: Permission) => {
    if (!permRepo) return;
    await api.delete(`/api/permissions/${perm.id}`);
    openPermissions(permRepo);
  };

  const openPackages = async (repo: Repository) => {
    setPkgRepo(repo);
    const { data } = await api.get<Package[]>(`/api/repositories/${repo.id}/packages`);
    setPackages(data);
  };

  return (
    <>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">Repositories</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreating({ name: '', type: 'hosted', upstreamUrl: '' })}
        >
          New repository
        </Button>
      </Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Paper>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Upstream URL</TableCell>
              <TableCell>Endpoint</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {repos.map((repo) => (
              <TableRow key={repo.id}>
                <TableCell>{repo.name}</TableCell>
                <TableCell>
                  <Chip
                    label={repo.type}
                    size="small"
                    color={repo.type === 'hosted' ? 'primary' : 'secondary'}
                  />
                </TableCell>
                <TableCell>{repo.upstream_url ?? '—'}</TableCell>
                <TableCell>
                  <code>/npm/{repo.name}/</code>
                </TableCell>
                <TableCell align="right">
                  <IconButton title="Packages" onClick={() => openPackages(repo)}>
                    <Inventory2Icon />
                  </IconButton>
                  <IconButton title="Permissions" onClick={() => openPermissions(repo)}>
                    <SecurityIcon />
                  </IconButton>
                  <IconButton onClick={() => remove(repo)}>
                    <DeleteIcon />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      {/* Создание репозитория */}
      <Dialog open={creating !== null} onClose={() => setCreating(null)} fullWidth maxWidth="xs">
        <DialogTitle>New repository</DialogTitle>
        {creating && (
          <DialogContent>
            <TextField
              label="Name"
              fullWidth
              margin="normal"
              value={creating.name}
              onChange={(e) => setCreating({ ...creating, name: e.target.value })}
              helperText="Latin letters, digits, dot, dash, underscore"
            />
            <FormControl fullWidth margin="normal">
              <InputLabel>Type</InputLabel>
              <Select
                label="Type"
                value={creating.type}
                onChange={(e) => setCreating({ ...creating, type: e.target.value as RepoType })}
              >
                <MenuItem value="hosted">hosted</MenuItem>
                <MenuItem value="proxy">proxy</MenuItem>
              </Select>
            </FormControl>
            {creating.type === 'proxy' && (
              <TextField
                label="Upstream URL"
                fullWidth
                margin="normal"
                placeholder="https://repo.maven.apache.org/maven2"
                value={creating.upstreamUrl}
                onChange={(e) => setCreating({ ...creating, upstreamUrl: e.target.value })}
              />
            )}
          </DialogContent>
        )}
        <DialogActions>
          <Button onClick={() => setCreating(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={create}
            disabled={!creating || !creating.name || (creating.type === 'proxy' && !creating.upstreamUrl)}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>

      {/* Права доступа */}
      <Dialog open={permRepo !== null} onClose={() => setPermRepo(null)} fullWidth maxWidth="sm">
        <DialogTitle>Permissions — {permRepo?.name}</DialogTitle>
        <DialogContent>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Role</TableCell>
                <TableCell>Access</TableCell>
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {permissions.map((perm) => (
                <TableRow key={perm.id}>
                  <TableCell>{perm.role.name}</TableCell>
                  <TableCell>
                    <Chip
                      label={perm.access_type}
                      size="small"
                      color={perm.access_type === 'WRITE' ? 'warning' : 'default'}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <IconButton size="small" onClick={() => removePermission(perm)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Box sx={{ display: 'flex', gap: 2, mt: 3 }}>
            <FormControl size="small" sx={{ minWidth: 160 }}>
              <InputLabel>Role</InputLabel>
              <Select
                label="Role"
                value={newPermRole}
                onChange={(e) => setNewPermRole(e.target.value as number)}
              >
                {roles.map((role) => (
                  <MenuItem key={role.id} value={role.id}>
                    {role.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel>Access</InputLabel>
              <Select
                label="Access"
                value={newPermAccess}
                onChange={(e) => setNewPermAccess(e.target.value as AccessType)}
              >
                <MenuItem value="READ">READ</MenuItem>
                <MenuItem value="WRITE">WRITE</MenuItem>
              </Select>
            </FormControl>
            <Button variant="outlined" onClick={addPermission} disabled={newPermRole === ''}>
              Add
            </Button>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPermRepo(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Пакеты репозитория */}
      <Dialog open={pkgRepo !== null} onClose={() => setPkgRepo(null)} fullWidth maxWidth="md">
        <DialogTitle>Packages — {pkgRepo?.name}</DialogTitle>
        <DialogContent>
          {packages.length === 0 ? (
            <Typography color="text.secondary">No packages yet.</Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Package</TableCell>
                  <TableCell>Version</TableCell>
                  <TableCell>Dependencies</TableCell>
                  <TableCell align="right">Size</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {packages.flatMap((pkg) =>
                  pkg.versions.map((ver) => (
                    <TableRow key={ver.id}>
                      <TableCell>
                        {pkg.name}
                        {pkg.dist_tags.latest === ver.version && (
                          <Chip label="latest" size="small" color="success" sx={{ ml: 1 }} />
                        )}
                      </TableCell>
                      <TableCell>{ver.version}</TableCell>
                      <TableCell>
                        {Object.entries(ver.dependencies).length === 0
                          ? '—'
                          : Object.entries(ver.dependencies)
                              .map(([dep, range]) => `${dep}@${range}`)
                              .join(', ')}
                      </TableCell>
                      <TableCell align="right">{(ver.size / 1024).toFixed(1)} KB</TableCell>
                    </TableRow>
                  )),
                )}
              </TableBody>
            </Table>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPkgRepo(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
