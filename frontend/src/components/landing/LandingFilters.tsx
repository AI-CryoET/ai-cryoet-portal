import { Box, Stack, TextField, Typography } from '@mui/material';

// Shared filter subcomponents. The full per-field filter UI now lives in
// `filters/` (FilterPanel + Section/Group/Property, registry-driven); this file
// keeps only the small primitives those components reuse.

// `dataset_type` is stored as a snake_case enum value (e.g. "single_molecule");
// render it as readable words without altering the underlying filter value.
export function prettyDatasetType(v: string): string {
  return v.replace(/_/g, ' ');
}

export function numOrUndef(s: string): number | undefined {
  return s === '' ? undefined : Number(s);
}

export function MinMaxRow({
  label,
  min,
  max,
  onMin,
  onMax,
  disabled
}: {
  readonly label: string;
  readonly min: number | undefined;
  readonly max: number | undefined;
  readonly onMin: (v: number | undefined) => void;
  readonly onMax: (v: number | undefined) => void;
  readonly disabled?: boolean;
}) {
  return (
    <Box>
      <Typography
        color={disabled ? 'text.disabled' : undefined}
        gutterBottom
        variant="body2"
      >
        {label}
      </Typography>
      <Stack direction="row" spacing={1}>
        <TextField
          disabled={disabled}
          onChange={e => onMin(numOrUndef(e.target.value))}
          placeholder="min"
          size="small"
          type="number"
          value={min ?? ''}
        />
        <TextField
          disabled={disabled}
          onChange={e => onMax(numOrUndef(e.target.value))}
          placeholder="max"
          size="small"
          type="number"
          value={max ?? ''}
        />
      </Stack>
    </Box>
  );
}
