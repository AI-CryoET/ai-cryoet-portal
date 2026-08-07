import AddIcon from '@mui/icons-material/Add';
import RemoveIcon from '@mui/icons-material/Remove';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Checkbox,
  FormControl,
  FormControlLabel,
  FormLabel,
  Radio,
  RadioGroup,
  Stack,
  Typography
} from '@mui/material';
import type { Field } from '~/utils/filterFields';
import type { SamplesSearchParams } from '~/utils/samplesSearch';
import type { FiltersOptionsOut } from '~/types';
import { MinMaxRow, prettyDatasetType } from '../LandingFilters';

type Props = {
  readonly field: Field;
  readonly options: FiltersOptionsOut;
  readonly values: SamplesSearchParams;
  readonly onChange: (patch: Partial<SamplesSearchParams>) => void;
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly disabled?: boolean;
};

// Per-field display transform. Only the display string changes; the stored
// value is always the raw option string.
function optionLabel(fieldKey: string, v: string): string {
  if (fieldKey === 'dataset_type') {
    return prettyDatasetType(v);
  }
  if (fieldKey === 'data_source') {
    return v.charAt(0).toUpperCase() + v.slice(1);
  }
  return v;
}

// A single filter property: a collapsed-by-default Accordion whose body renders
// by field.kind. Selection lives entirely in `values` (URL); emits patches up.
export function FilterProperty({
  field,
  options,
  values,
  onChange,
  expanded,
  onToggle,
  disabled
}: Props) {
  const v = values as Record<string, unknown>;

  return (
    <Accordion
      disableGutters
      disabled={disabled}
      elevation={0}
      expanded={expanded}
      onChange={onToggle}
      square
      sx={{
        '&:before': { display: 'none' },
        borderBottom: '1px solid',
        borderColor: 'divider'
      }}
    >
      <AccordionSummary
        aria-label={field.label}
        expandIcon={
          expanded ? (
            <RemoveIcon fontSize="small" />
          ) : (
            <AddIcon fontSize="small" />
          )
        }
        sx={{
          px: 0,
          minHeight: 40,
          '& .MuiAccordionSummary-content': { my: 0.5 }
        }}
      >
        <Typography fontWeight={600} variant="body2">
          {field.label}
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 0, pt: 0 }}>
        {renderBody(field, options, v, onChange, disabled)}
      </AccordionDetails>
    </Accordion>
  );
}

const noValues = (
  <Typography color="text.secondary" fontStyle="italic" variant="body2">
    No values for this property have been provided or derived
  </Typography>
);

function renderBody(
  field: Field,
  options: FiltersOptionsOut,
  v: Record<string, unknown>,
  onChange: (patch: Partial<SamplesSearchParams>) => void,
  disabled?: boolean
) {
  switch (field.kind) {
    case 'text': {
      const opts = options.categorical[field.key] ?? [];
      if (opts.length === 0) {
        return noValues;
      }
      const selected = (v[field.key] as string[] | undefined) ?? [];
      const toggle = (opt: string) => {
        const next = selected.includes(opt)
          ? selected.filter(s => s !== opt)
          : [...selected, opt];
        onChange({ [field.key]: next.length ? next : undefined });
      };
      return (
        <FormControl
          component="fieldset"
          sx={{ width: '100%' }}
          variant="standard"
        >
          <FormLabel
            component="legend"
            sx={{
              position: 'absolute',
              width: 1,
              height: 1,
              overflow: 'hidden',
              clip: 'rect(0 0 0 0)'
            }}
          >
            {field.label}
          </FormLabel>
          <Stack>
            {opts.map(opt => (
              <FormControlLabel
                control={
                  <Checkbox
                    checked={selected.includes(opt)}
                    disabled={disabled}
                    onChange={() => toggle(opt)}
                    size="small"
                  />
                }
                key={opt}
                label={
                  <Typography variant="body2">
                    {optionLabel(field.key, opt)}
                  </Typography>
                }
                sx={{ ml: 0 }}
              />
            ))}
          </Stack>
        </FormControl>
      );
    }
    case 'range': {
      const bounds = options.ranges[field.key];
      if (!bounds || (bounds.min == null && bounds.max == null)) {
        return noValues;
      }
      return (
        <MinMaxRow
          disabled={disabled}
          label={
            bounds && (bounds.min != null || bounds.max != null)
              ? `${bounds.min ?? ''}–${bounds.max ?? ''}`
              : ''
          }
          max={v[`${field.key}_max`] as number | undefined}
          min={v[`${field.key}_min`] as number | undefined}
          onMax={val => onChange({ [`${field.key}_max`]: val })}
          onMin={val => onChange({ [`${field.key}_min`]: val })}
        />
      );
    }
    case 'boolean': {
      const cur = v[field.key] as boolean | undefined;
      const strVal = cur === true ? 'yes' : cur === false ? 'no' : 'any';
      return (
        <FormControl
          component="fieldset"
          disabled={disabled}
          variant="standard"
        >
          <FormLabel
            component="legend"
            sx={{
              position: 'absolute',
              width: 1,
              height: 1,
              overflow: 'hidden',
              clip: 'rect(0 0 0 0)'
            }}
          >
            {field.label}
          </FormLabel>
          <RadioGroup
            onChange={e => {
              const val =
                e.target.value === 'yes'
                  ? true
                  : e.target.value === 'no'
                    ? false
                    : undefined;
              onChange({ [field.key]: val });
            }}
            row
            value={strVal}
          >
            <FormControlLabel
              control={<Radio size="small" />}
              label="Yes"
              value="yes"
            />
            <FormControlLabel
              control={<Radio size="small" />}
              label="No"
              value="no"
            />
            <FormControlLabel
              control={<Radio size="small" />}
              label="Any"
              value="any"
            />
          </RadioGroup>
        </FormControl>
      );
    }
    case 'existence': {
      const checked = v[field.key] === true;
      return (
        <FormControlLabel
          control={
            <Checkbox
              checked={checked}
              disabled={disabled}
              onChange={e =>
                onChange({ [field.key]: e.target.checked ? true : undefined })
              }
              size="small"
            />
          }
          label={<Typography variant="body2">{field.label}</Typography>}
          sx={{ ml: 0 }}
        />
      );
    }
  }
}
