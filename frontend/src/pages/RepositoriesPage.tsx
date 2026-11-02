import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
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
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import Inventory2Icon from '@mui/icons-material/Inventory2';
import SecurityIcon from '@mui/icons-material/Security';
import { api, apiErrorMessage } from '../api';
import type { AccessGrant, Package, Repository, RepoType, Role, User } from '../types';

interface CreateState {
  name: string;
  type: RepoType;
  upstreamUrl: string;
  allowOverwrite: boolean;
}

export default function RepositoriesPage() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<CreateState | null>(null);
  const [accessRepo, setAccessRepo] = useState<Repository | null>(null);
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [newGrantUser, setNewGrantUser] = useState<number | ''>('');
  const [newGrantRole, setNewGrantRole] = useState<number | ''>('');
  const [pkgRepo, setPkgRepo] = useState<Repository | null>(null);
  const [packages, setPackages] = useState<Package[]>([]);

  const reload = () => {
    api.get<Repository[]>('/api/repositories').then((res) => setRepos(res.data)).catch((e) => setError(apiErrorMessage(e)));
    api.get<Role[]>('/api/roles').then((res) => setRoles(res.data)).catch(() => {});
    api.get<User[]>('/api/users').then((res) => setUsers(res.data)).catch(() => {});
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
        allow_overwrite: creating.allowOverwrite,
      });
      setCreating(null);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const remove = async (repo: Repository) => {
    if (!window.confirm(`Delete repository "${repo.name}" and all its packages?`)) return;
    try {
      await api.delete(`/api/repositories/${repo.id}`);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const toggleOverwrite = async (repo: Repository) => {
    try {
      await api.patch(`/api/repositories/${repo.id}`, { allow_overwrite: !repo.allow_overwrite });
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  // --- Access (назначение ролей) ---
  const openAccess = async (repo: Repository) => {
    setAccessRepo(repo);
    setNewGrantUser('');
    setNewGrantRole('');
    const { data } = await api.get<AccessGrant[]>(`/api/repositories/${repo.id}/access`);
    setGrants(data);
  };

  const addGrant = async () => {
    if (!accessRepo || newGrantUser === '' || newGrantRole === '') return;
    try {
      await api.post(`/api/repositories/${accessRepo.id}/access`, {
        user_id: newGrantUser,
        role_id: newGrantRole,
      });
      openAccess(accessRepo);
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const removeGrant = async (grant: AccessGrant) => {
    if (!accessRepo) return;
    await api.delete(`/api/access/${grant.id}`);
    openAccess(accessRepo);
  };

  // --- Packages ---
  const openPackages = async (repo: Repository) => {
    setPkgRepo(repo);
    const { data } = await api.get<Package[]>(`/api/repositories/${repo.id}/packages`);
    setPackages(data);
  };

  const removeVersion = async (versionId: number, label: string) => {
    if (!pkgRepo || !window.confirm(`Delete ${label}?`)) return;
    try {
      await api.delete(`/api/package-versions/${versionId}`);
      openPackages(pkgRepo);
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  return (
    <>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">Repositories</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() =>
            setCreating({ name: '', type: 'hosted', upstreamUrl: '', allowOverwrite: false })
          }
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
              <TableCell>Overwrite</TableCell>
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
                  {repo.type === 'hosted' ? (
                    <Tooltip title="Allow overwriting existing versions (requires UPDATE permission)">
                      <Checkbox
                        checked={repo.allow_overwrite}
                        onChange={() => toggleOverwrite(repo)}
                        size="small"
                      />
                    </Tooltip>
                  ) : (
                    '—'
                  )}
                </TableCell>
                <TableCell>
                  <code>/npm/{repo.name}/</code>
                </TableCell>
                <TableCell align="right">
                  <IconButton title="Packages" onClick={() => openPackages(repo)}>
                    <Inventory2Icon />
                  </IconButton>
                  <IconButton title="Access" onClick={() => openAccess(repo)}>
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
                placeholder="https://registry.npmjs.org"
                value={creating.upstreamUrl}
                onChange={(e) => setCreating({ ...creating, upstreamUrl: e.target.value })}
              />
            )}
            {creating.type === 'hosted' && (
              <FormControlLabel
                control={
                  <Checkbox
                    checked={creating.allowOverwrite}
                    onChange={(e) => setCreating({ ...creating, allowOverwrite: e.target.checked })}
                  />
                }
                label="Allow overwriting existing versions"
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

      {/* Назначения ролей */}
      <Dialog open={accessRepo !== null} onClose={() => setAccessRepo(null)} fullWidth maxWidth="sm">
        <DialogTitle>Access — {accessRepo?.name}</DialogTitle>
        <DialogContent>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>User</TableCell>
                <TableCell>Role</TableCell>
                <TableCell>Permissions</TableCell>
                <TableCell align="right" />
              </TableRow>
            </TableHead>
            <TableBody>
              {grants.map((grant) => (
                <TableRow key={grant.id}>
                  <TableCell>{grant.user.login}</TableCell>
                  <TableCell>{grant.role.name}</TableCell>
                  <TableCell>
                    {grant.role.permissions.map((perm) => (
                      <Chip key={perm} label={perm} size="small" sx={{ mr: 0.5 }} />
                    ))}
                  </TableCell>
                  <TableCell align="right">
                    <IconButton size="small" onClick={() => removeGrant(grant)}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Box sx={{ display: 'flex', gap: 2, mt: 3 }}>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>User</InputLabel>
              <Select
                label="User"
                value={newGrantUser}
                onChange={(e) => setNewGrantUser(e.target.value as number)}
              >
                {users
                  .filter((u) => !u.is_superadmin)
                  .map((u) => (
                    <MenuItem key={u.id} value={u.id}>
                      {u.login}
                    </MenuItem>
                  ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Role</InputLabel>
              <Select
                label="Role"
                value={newGrantRole}
                onChange={(e) => setNewGrantRole(e.target.value as number)}
              >
                {roles.map((role) => (
                  <MenuItem key={role.id} value={role.id}>
                    {role.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="outlined"
              onClick={addGrant}
              disabled={newGrantUser === '' || newGrantRole === ''}
            >
              Add
            </Button>
          </Box>
          <Typography color="text.secondary" sx={{ mt: 2 }} variant="body2">
            Multiple roles for the same user sum their permissions. Superadmins always have
            full access and are not listed here.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAccessRepo(null)}>Close</Button>
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
                  <TableCell align="right" />
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
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          title="Delete version"
                          onClick={() => removeVersion(ver.id, `${pkg.name}@${ver.version}`)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
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
