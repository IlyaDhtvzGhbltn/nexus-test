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
  FormControlLabel,
  FormGroup,
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
import EditIcon from '@mui/icons-material/Edit';
import { api, apiErrorMessage } from '../api';
import { ALL_PERMISSIONS, PermissionType, Role } from '../types';

const PERMISSION_HINTS: Record<PermissionType, string> = {
  CREATE: 'publish new versions',
  READ: 'download packages and version metadata',
  UPDATE: 'overwrite existing versions (if repo policy allows)',
  DELETE: 'delete versions/packages',
  LIST: 'search and list packages',
  ADMIN: 'change repository settings',
};

interface EditorState {
  role: Role | null; // null = создание
  name: string;
  permissions: PermissionType[];
}

export default function RolesPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);

  const reload = () => {
    api.get<Role[]>('/api/roles').then((res) => setRoles(res.data)).catch((e) => setError(apiErrorMessage(e)));
  };

  useEffect(reload, []);

  const save = async () => {
    if (!editor) return;
    setError(null);
    try {
      if (editor.role === null) {
        await api.post('/api/roles', { name: editor.name.trim(), permissions: editor.permissions });
      } else {
        await api.patch(`/api/roles/${editor.role.id}`, { permissions: editor.permissions });
      }
      setEditor(null);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const remove = async (role: Role) => {
    if (
      !window.confirm(
        `Delete role "${role.name}"? All its repository assignments will be removed as well.`,
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

  const togglePermission = (perm: PermissionType) => {
    if (!editor) return;
    const permissions = editor.permissions.includes(perm)
      ? editor.permissions.filter((p) => p !== perm)
      : [...editor.permissions, perm];
    setEditor({ ...editor, permissions });
  };

  return (
    <>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">Roles</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setEditor({ role: null, name: '', permissions: [] })}
        >
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
              <TableCell>Permissions</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {roles.map((role) => (
              <TableRow key={role.id}>
                <TableCell>{role.name}</TableCell>
                <TableCell>
                  {role.permissions.length === 0
                    ? '—'
                    : role.permissions.map((perm) => (
                        <Chip key={perm} label={perm} size="small" sx={{ mr: 0.5 }} />
                      ))}
                </TableCell>
                <TableCell align="right">
                  <IconButton
                    onClick={() =>
                      setEditor({ role, name: role.name, permissions: [...role.permissions] })
                    }
                  >
                    <EditIcon />
                  </IconButton>
                  <IconButton onClick={() => remove(role)}>
                    <DeleteIcon />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
      <Typography color="text.secondary" sx={{ mt: 2 }} variant="body2">
        A role is a named set of atomic permissions. It has effect only when assigned to a user
        on a specific repository (shield icon on the Repositories page). Multiple roles on the
        same repository sum their permissions.
      </Typography>

      <Dialog open={editor !== null} onClose={() => setEditor(null)} fullWidth maxWidth="xs">
        <DialogTitle>{editor?.role ? `Edit ${editor.role.name}` : 'New role'}</DialogTitle>
        {editor && (
          <DialogContent>
            {editor.role === null && (
              <TextField
                label="Name"
                fullWidth
                margin="normal"
                value={editor.name}
                onChange={(e) => setEditor({ ...editor, name: e.target.value })}
                helperText="e.g. developer, ci_runner, repo_admin"
                autoFocus
              />
            )}
            <Typography variant="subtitle2" sx={{ mt: 1 }}>
              Permissions
            </Typography>
            <FormGroup>
              {ALL_PERMISSIONS.map((perm) => (
                <FormControlLabel
                  key={perm}
                  control={
                    <Checkbox
                      checked={editor.permissions.includes(perm)}
                      onChange={() => togglePermission(perm)}
                    />
                  }
                  label={`${perm} — ${PERMISSION_HINTS[perm]}`}
                />
              ))}
            </FormGroup>
          </DialogContent>
        )}
        <DialogActions>
          <Button onClick={() => setEditor(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={save}
            disabled={!editor || (editor.role === null && editor.name.trim().length < 2)}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
