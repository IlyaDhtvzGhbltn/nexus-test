import { useCallback, useEffect, useState } from 'react';
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
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import BlockIcon from '@mui/icons-material/Block';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import DeleteIcon from '@mui/icons-material/Delete';
import GroupIcon from '@mui/icons-material/Group';
import { api, apiErrorMessage } from '../api';
import type {
  DownloadLog,
  OperatorLog,
  QuarantineStatus,
  SecurityVersion,
  WhitelistRule,
} from '../types';

const STATUS_COLOR: Record<QuarantineStatus, 'default' | 'success' | 'error' | 'warning'> = {
  UNKNOWN: 'default',
  CLEAN: 'success',
  QUARANTINED: 'error',
  WHITELISTED: 'warning',
};

export function StatusChip({ status }: { status: QuarantineStatus }) {
  return <Chip label={status} size="small" color={STATUS_COLOR[status]} />;
}

function fmt(ts: string) {
  return new Date(ts).toLocaleString();
}

export default function SecurityPage() {
  const [tab, setTab] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // --- Versions ---
  const [versions, setVersions] = useState<SecurityVersion[]>([]);
  const [statusFilter, setStatusFilter] = useState<QuarantineStatus | ''>('');
  const [packageFilter, setPackageFilter] = useState('');

  // --- Whitelist ---
  const [whitelist, setWhitelist] = useState<WhitelistRule[]>([]);
  const [wlDialog, setWlDialog] = useState<{ pkg: string; version: string; reason: string } | null>(null);

  // --- Audit ---
  const [downloads, setDownloads] = useState<DownloadLog[]>([]);
  const [dlPackage, setDlPackage] = useState('');
  const [dlUser, setDlUser] = useState('');
  const [operations, setOperations] = useState<OperatorLog[]>([]);

  // --- "Кто скачал" ---
  const [affected, setAffected] = useState<{ version: SecurityVersion; rows: DownloadLog[] } | null>(null);

  const loadVersions = useCallback(() => {
    const params = new URLSearchParams();
    if (statusFilter) params.set('status_filter', statusFilter);
    if (packageFilter) params.set('package', packageFilter);
    api
      .get<SecurityVersion[]>(`/api/security/versions?${params}`)
      .then((res) => setVersions(res.data))
      .catch((e) => setError(apiErrorMessage(e)));
  }, [statusFilter, packageFilter]);

  const loadWhitelist = useCallback(() => {
    api.get<WhitelistRule[]>('/api/security/whitelist').then((res) => setWhitelist(res.data)).catch(() => {});
  }, []);

  const loadDownloads = useCallback(() => {
    const params = new URLSearchParams();
    if (dlPackage) params.set('package', dlPackage);
    if (dlUser) params.set('user', dlUser);
    api.get<DownloadLog[]>(`/api/audit/downloads?${params}`).then((res) => setDownloads(res.data)).catch(() => {});
  }, [dlPackage, dlUser]);

  const loadOperations = useCallback(() => {
    api.get<OperatorLog[]>('/api/audit/operations').then((res) => setOperations(res.data)).catch(() => {});
  }, []);

  useEffect(loadVersions, [loadVersions]);
  useEffect(loadWhitelist, [loadWhitelist]);
  useEffect(loadDownloads, [loadDownloads]);
  useEffect(loadOperations, [loadOperations]);

  const setStatus = async (v: SecurityVersion, status: QuarantineStatus) => {
    setError(null);
    try {
      await api.post(`/api/security/versions/${v.id}/status`, { status });
      loadVersions();
      loadOperations();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const showAffected = async (v: SecurityVersion) => {
    const { data } = await api.get<DownloadLog[]>(
      `/api/audit/downloads?package=${encodeURIComponent(v.package_name)}&version=${encodeURIComponent(v.version)}`,
    );
    setAffected({ version: v, rows: data });
  };

  const addWhitelist = async () => {
    if (!wlDialog) return;
    setError(null);
    try {
      await api.post('/api/security/whitelist', {
        package_name: wlDialog.pkg,
        version: wlDialog.version,
        reason: wlDialog.reason,
      });
      setWlDialog(null);
      loadWhitelist();
      loadVersions();
      loadOperations();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const removeWhitelist = async (rule: WhitelistRule) => {
    if (!window.confirm(`Remove whitelist rule for ${rule.package_name}@${rule.version}?`)) return;
    await api.delete(`/api/security/whitelist/${rule.id}`);
    loadWhitelist();
    loadVersions();
    loadOperations();
  };

  return (
    <>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Security
      </Typography>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Package versions" />
        <Tab label="Whitelist" />
        <Tab label="Downloads log" />
        <Tab label="Operator log" />
      </Tabs>

      {tab === 0 && (
        <>
          <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Status</InputLabel>
              <Select
                label="Status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as QuarantineStatus | '')}
              >
                <MenuItem value="">all</MenuItem>
                {(['UNKNOWN', 'CLEAN', 'QUARANTINED', 'WHITELISTED'] as QuarantineStatus[]).map((s) => (
                  <MenuItem key={s} value={s}>
                    {s}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              label="Package"
              value={packageFilter}
              onChange={(e) => setPackageFilter(e.target.value)}
            />
          </Box>
          <Paper>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Repository</TableCell>
                  <TableCell>Package</TableCell>
                  <TableCell>Version</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Findings</TableCell>
                  <TableCell>Scanned</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {versions.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell>{v.repository_name}</TableCell>
                    <TableCell>{v.package_name}</TableCell>
                    <TableCell>{v.version}</TableCell>
                    <TableCell>
                      <StatusChip status={v.quarantine_status} />
                    </TableCell>
                    <TableCell>
                      {v.scan_findings.length === 0 ? (
                        '—'
                      ) : (
                        <Tooltip
                          title={v.scan_findings
                            .slice(0, 10)
                            .map((f) => `${f.severity}: ${f.id} (${f.package}@${f.installed})`)
                            .join('; ')}
                        >
                          <Chip label={v.scan_findings.length} size="small" color="error" />
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell>{v.last_scanned_at ? fmt(v.last_scanned_at) : 'never'}</TableCell>
                    <TableCell align="right">
                      {v.quarantine_status !== 'WHITELISTED' && (
                        <>
                          <Tooltip title="Mark CLEAN (false positive)">
                            <IconButton size="small" onClick={() => setStatus(v, 'CLEAN')}>
                              <CheckCircleIcon fontSize="small" color="success" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title="Quarantine (block downloads)">
                            <IconButton size="small" onClick={() => setStatus(v, 'QUARANTINED')}>
                              <BlockIcon fontSize="small" color="error" />
                            </IconButton>
                          </Tooltip>
                        </>
                      )}
                      <Tooltip title="Who downloaded this version">
                        <IconButton size="small" onClick={() => showAffected(v)}>
                          <GroupIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Add to whitelist">
                        <IconButton
                          size="small"
                          onClick={() =>
                            setWlDialog({ pkg: v.package_name, version: v.version, reason: '' })
                          }
                        >
                          <AddIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        </>
      )}

      {tab === 1 && (
        <>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setWlDialog({ pkg: '', version: '', reason: '' })}
            >
              New rule
            </Button>
          </Box>
          <Paper>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Package</TableCell>
                  <TableCell>Version</TableCell>
                  <TableCell>Reason</TableCell>
                  <TableCell>Created by</TableCell>
                  <TableCell>Created at</TableCell>
                  <TableCell align="right" />
                </TableRow>
              </TableHead>
              <TableBody>
                {whitelist.map((rule) => (
                  <TableRow key={rule.id}>
                    <TableCell>{rule.package_name}</TableCell>
                    <TableCell>{rule.version}</TableCell>
                    <TableCell>{rule.reason}</TableCell>
                    <TableCell>{rule.created_by_login}</TableCell>
                    <TableCell>{fmt(rule.created_at)}</TableCell>
                    <TableCell align="right">
                      <IconButton size="small" onClick={() => removeWhitelist(rule)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        </>
      )}

      {tab === 2 && (
        <>
          <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
            <TextField size="small" label="Package" value={dlPackage} onChange={(e) => setDlPackage(e.target.value)} />
            <TextField size="small" label="User" value={dlUser} onChange={(e) => setDlUser(e.target.value)} />
          </Box>
          <Paper>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>When</TableCell>
                  <TableCell>User</TableCell>
                  <TableCell>Package</TableCell>
                  <TableCell>Version</TableCell>
                  <TableCell>Repository</TableCell>
                  <TableCell>User-Agent</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {downloads.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{fmt(row.downloaded_at)}</TableCell>
                    <TableCell>{row.user_login}</TableCell>
                    <TableCell>{row.package_name}</TableCell>
                    <TableCell>{row.package_version}</TableCell>
                    <TableCell>{row.repository_name}</TableCell>
                    <TableCell sx={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {row.user_agent}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        </>
      )}

      {tab === 3 && (
        <Paper>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>When</TableCell>
                <TableCell>Actor</TableCell>
                <TableCell>Action</TableCell>
                <TableCell>Target</TableCell>
                <TableCell>Details</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {operations.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{fmt(row.created_at)}</TableCell>
                  <TableCell>{row.actor_login}</TableCell>
                  <TableCell>
                    <Chip label={row.action} size="small" />
                  </TableCell>
                  <TableCell>{row.target}</TableCell>
                  <TableCell>
                    <code>{JSON.stringify(row.details)}</code>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      {/* Диалог: кто скачал версию */}
      <Dialog open={affected !== null} onClose={() => setAffected(null)} fullWidth maxWidth="sm">
        <DialogTitle>
          Downloads of {affected?.version.package_name}@{affected?.version.version}
        </DialogTitle>
        <DialogContent>
          {affected && affected.rows.length === 0 ? (
            <Typography color="text.secondary">Nobody downloaded this version.</Typography>
          ) : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>When</TableCell>
                  <TableCell>User</TableCell>
                  <TableCell>User-Agent</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {affected?.rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>{fmt(row.downloaded_at)}</TableCell>
                    <TableCell>{row.user_login}</TableCell>
                    <TableCell>{row.user_agent}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {affected && affected.version.quarantine_status === 'QUARANTINED' && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              These users downloaded the version before it was quarantined — notify them.
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAffected(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Диалог: новое whitelist-правило */}
      <Dialog open={wlDialog !== null} onClose={() => setWlDialog(null)} fullWidth maxWidth="xs">
        <DialogTitle>Add to whitelist</DialogTitle>
        {wlDialog && (
          <DialogContent>
            <TextField
              label="Package"
              fullWidth
              margin="normal"
              value={wlDialog.pkg}
              onChange={(e) => setWlDialog({ ...wlDialog, pkg: e.target.value })}
            />
            <TextField
              label="Exact version"
              fullWidth
              margin="normal"
              value={wlDialog.version}
              onChange={(e) => setWlDialog({ ...wlDialog, version: e.target.value })}
            />
            <TextField
              label="Reason"
              fullWidth
              multiline
              minRows={2}
              margin="normal"
              value={wlDialog.reason}
              onChange={(e) => setWlDialog({ ...wlDialog, reason: e.target.value })}
            />
          </DialogContent>
        )}
        <DialogActions>
          <Button onClick={() => setWlDialog(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={addWhitelist}
            disabled={!wlDialog || !wlDialog.pkg || !wlDialog.version || wlDialog.reason.length < 3}
          >
            Add
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
