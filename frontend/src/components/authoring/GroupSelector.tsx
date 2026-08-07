import { MenuItem, TextField } from '@mui/material';

/**
 * Picks which Reconstructions/<group>/ folder's reconstruction.toml is being
 * authored. One acquisition holds many groups and each has its own file, so
 * the selector is this form's record picker, not a filter.
 *
 * "New group" is the empty value rather than a separate button: nothing in
 * this stack can create a folder (every form ends in a browser download the
 * researcher files by hand), so a new group is simply "no group selected yet"
 * — an empty form whose placement hint names the folder to create. Keeping it
 * inside the same control means the selector always shows the truth about
 * which group the form is on.
 */
export function GroupSelector({
  groups,
  value,
  onChange
}: {
  readonly groups: string[];
  readonly value: string;
  readonly onChange: (group: string) => void;
}) {
  // The deep link names a group before the list has loaded; without it as an
  // option MUI renders a blank box and warns about an out-of-range value.
  const options =
    value && !groups.includes(value) ? [value, ...groups] : groups;
  return (
    <TextField
      helperText="Which Reconstructions/{id}/ folder this file belongs to"
      label="Group"
      onChange={e => onChange(e.target.value)}
      select
      size="small"
      sx={{ minWidth: 260, alignSelf: 'flex-start' }}
      value={value}
    >
      <MenuItem value="">
        <em>New group…</em>
      </MenuItem>
      {options.map(g => (
        <MenuItem key={g} value={g}>
          {g}
        </MenuItem>
      ))}
    </TextField>
  );
}
