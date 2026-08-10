import { TextField, InputAdornment } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';

// Controlled free-text search box for the browse pages. The URL (`q`) is the
// source of truth: value comes from the URL, onChange writes it back on every
// keystroke; the parent debounces the *query* (useDebounce), mirroring the
// warnings-page search (OutstandingIssuesTable).
export function SampleSearchField({
  value,
  onChange
}: {
  readonly value: string;
  readonly onChange: (q: string) => void;
}) {
  return (
    <TextField
      onChange={e => onChange(e.target.value)}
      placeholder="Search ids (sample, acquisition, tomogram, annotation)"
      size="small"
      slotProps={{
        input: {
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          )
        }
      }}
      sx={{
        minWidth: { xs: '100%', sm: 360 },
        maxWidth: 520,
        bgcolor: 'common.white'
      }}
      value={value}
    />
  );
}
