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
  Switch,
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
import type { Role, User } from '../types';

interface EditorState {
  user: User | null; // null = создание нового
  login: string;
  password: string;
  isActive: boolean;
  roleIds: number[];
}

const emptyEditor: EditorState = { user: null, login: '', password: '', isActive: true, roleIds: [] };

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    api.get<User[]>('/api/users').then((res) => setUsers(res.data)).catch((e) => setError(apiErrorMessage(e)));
    api.get<Role[]>('/api/roles').then((res) => setRoles(res.data)).catch(() => {});
  };

  useEffect(reload, []);

  const save = async () => {
    if (!editor) return;
    setError(null);
    try {
      if (editor.user === null) {
        await api.post('/api/users', {
          login: editor.login,
          password: editor.password,
          role_ids: editor.roleIds,
        });
      } else {
        await api.patch(`/api/users/${editor.user.id}`, {
          password: editor.password || null,
          is_active: editor.isActive,
          role_ids: editor.roleIds,
        });
      }
      setEditor(null);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const remove = async (user: User) => {
    if (!window.confirm(`Delete user "${user.login}"?`)) return;
    try {
      await api.delete(`/api/users/${user.id}`);
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  };

  const toggleRole = (roleId: number) => {
    if (!editor) return;
    const roleIds = editor.roleIds.includes(roleId)
      ? editor.roleIds.filter((id) => id !== roleId)
      : [...editor.roleIds, roleId];
    setEditor({ ...editor, roleIds });
  };

  return (
    <>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h5">Users</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setEditor({ ...emptyEditor })}>
          New user
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
              <TableCell>Login</TableCell>
              <TableCell>Roles</TableCell>
              <TableCell>Active</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {users.map((user) => (
              <TableRow key={user.id}>
                <TableCell>{user.login}</TableCell>
                <TableCell>
                  {user.roles.map((role) => (
                    <Chip key={role.id} label={role.name} size="small" sx={{ mr: 0.5 }} />
                  ))}
                </TableCell>
                <TableCell>{user.is_active ? 'Yes' : 'No'}</TableCell>
                <TableCell align="right">
                  <IconButton
                    onClick={() =>
                      setEditor({
                        user,
                        login: user.login,
                        password: '',
                        isActive: user.is_active,
                        roleIds: user.roles.map((r) => r.id),
                      })
                    }
                  >
                    <EditIcon />
                  </IconButton>
                  <IconButton onClick={() => remove(user)}>
                    <DeleteIcon />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>

      <Dialog open={editor !== null} onClose={() => setEditor(null)} fullWidth maxWidth="xs">
        <DialogTitle>{editor?.user ? `Edit ${editor.user.login}` : 'New user'}</DialogTitle>
        {editor && (
          <DialogContent>
            {editor.user === null && (
              <TextField
                label="Login"
                fullWidth
                margin="normal"
                value={editor.login}
                onChange={(e) => setEditor({ ...editor, login: e.target.value })}
              />
            )}
            <TextField
              label={editor.user ? 'New password (leave blank to keep)' : 'Password'}
              type="password"
              fullWidth
              margin="normal"
              value={editor.password}
              onChange={(e) => setEditor({ ...editor, password: e.target.value })}
            />
            {editor.user !== null && (
              <FormControlLabel
                control={
                  <Switch
                    checked={editor.isActive}
                    onChange={(e) => setEditor({ ...editor, isActive: e.target.checked })}
                  />
                }
                label="Active"
              />
            )}
            <Typography variant="subtitle2" sx={{ mt: 2 }}>
              Roles
            </Typography>
            <FormGroup>
              {roles.map((role) => (
                <FormControlLabel
                  key={role.id}
                  control={
                    <Checkbox checked={editor.roleIds.includes(role.id)} onChange={() => toggleRole(role.id)} />
                  }
                  label={role.name}
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
            disabled={!editor || (editor.user === null && (!editor.login || !editor.password))}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
