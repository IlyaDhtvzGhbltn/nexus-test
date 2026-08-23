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
  IconButton,
  Paper,
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
import { api, apiErrorMessage } from '../api';
import type { Role } from '../types';

export default function RolesPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState<string | null>(null); // null = диалог закрыт

  const reload = () => {
    api.get<Role[]>('/api/roles').then((res) => setRoles(res.data)).catch((e) => setError(apiErrorMessage(e)));
  };

  useEffect(reload, []);

  const create = async () => {
    if (!newName) return;
    setError(null);
    try {
      await api.post('/api/roles', { name: newName.trim() });
      setNewName(null);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const remove = async (role: Role) => {
    if (
      !window.confirm(
        `Delete role "${role.name}"? Its repository permissions and user assignments will be removed as well.`,
      )
    )
      return;
    try {
      await api.delete(`/api/roles/${role.id}`);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  return (
    <>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">Roles</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setNewName('')}>
          New role
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
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {roles.map((role) => (
              <TableRow key={role.id}>
                <TableCell>
                  {role.name}
                  {role.name === 'ADMIN' && (
                    <Chip label="built-in, full access" size="small" color="primary" sx={{ ml: 1 }} />
                  )}
                </TableCell>
                <TableCell align="right">
                  <IconButton
                    onClick={() => remove(role)}
                    disabled={role.name === 'ADMIN'}
                    title={role.name === 'ADMIN' ? 'The ADMIN role cannot be deleted' : 'Delete role'}
                  >
                    <DeleteIcon />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
      <Typography color="text.secondary" sx={{ mt: 2 }} variant="body2">
        A role by itself grants nothing: assign it to users on the Users page, then grant it
        READ/WRITE per repository via the shield icon on the Repositories page. ADMIN is the only
        built-in role and always has full access.
      </Typography>

      <Dialog open={newName !== null} onClose={() => setNewName(null)} fullWidth maxWidth="xs">
        <DialogTitle>New role</DialogTitle>
        <DialogContent>
          <TextField
            label="Name"
            fullWidth
            margin="normal"
            value={newName ?? ''}
            onChange={(e) => setNewName(e.target.value)}
            helperText="2–64 chars: latin letters, digits, dash, underscore (e.g. DEVELOPER, CI_BOT, TEAM_PAYMENTS)"
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNewName(null)}>Cancel</Button>
          <Button variant="contained" onClick={create} disabled={!newName || newName.trim().length < 2}>
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
