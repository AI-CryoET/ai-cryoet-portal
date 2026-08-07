// Shared bits used by the schema explorer: the hybrid control bar, the pure
// filter, the source badge, and the fields table.
import {
  Box,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography
} from '@mui/material';
import EditNoteIcon from '@mui/icons-material/EditNote';
import SettingsSuggestIcon from '@mui/icons-material/SettingsSuggest';
import type { Arm, SchemaEntity, SchemaField, SourceKind } from './schemaData';

export type SourceFilter = 'all' | 'authored' | 'derived';

export interface Controls {
  arm: Arm;
  chromatin: boolean; // true = chromatin, false = non-chromatin
  source: SourceFilter;
}

// Gate an entity by the arm + project toggles.
function entityVisible(entity: SchemaEntity, c: Controls): boolean {
  if (entity.arm && entity.arm !== c.arm) {
    return false;
  }
  if (entity.chromatinOnly && !c.chromatin) {
    return false;
  }
  return true;
}

function fieldVisible(f: SchemaField, source: SourceFilter): boolean {
  return source === 'all' || f.kind === source;
}

// Filter the tree: drop gated entities, filter each entity's fields by source,
// recurse into children, and prune entities with no visible fields or children.
export function filterTree(
  entities: SchemaEntity[],
  c: Controls
): SchemaEntity[] {
  return entities.flatMap(entity => {
    if (!entityVisible(entity, c)) {
      return [];
    }
    const fields = entity.fields.filter(f => fieldVisible(f, c.source));
    const children = entity.children
      ? filterTree(entity.children, c)
      : undefined;
    if (fields.length === 0 && (!children || children.length === 0)) {
      return [];
    }
    return [{ ...entity, fields, children }];
  });
}

export function SourceBadge({
  source,
  kind
}: {
  readonly source: string;
  readonly kind: SourceKind;
}) {
  const authored = kind === 'authored';
  return (
    <Chip
      color={authored ? 'primary' : 'default'}
      icon={authored ? <EditNoteIcon /> : <SettingsSuggestIcon />}
      label={source}
      size="small"
      sx={{ fontFamily: 'monospace', fontSize: '0.72rem' }}
      variant="outlined"
    />
  );
}

export function FieldsTable({ fields }: { readonly fields: SchemaField[] }) {
  return (
    <Table size="small" sx={{ '& td, & th': { verticalAlign: 'top' } }}>
      <TableHead>
        <TableRow>
          <TableCell sx={{ fontWeight: 700 }}>Field</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Type</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Source</TableCell>
          <TableCell sx={{ fontWeight: 700 }}>Notes</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {fields.map(f => (
          <TableRow key={f.field}>
            <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
              {f.field}
            </TableCell>
            <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
              {f.type}
            </TableCell>
            <TableCell>
              <SourceBadge kind={f.kind} source={f.source} />
            </TableCell>
            <TableCell>
              <Typography color="text.secondary" variant="body2">
                {f.notes}
              </Typography>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// Aggregated view: one section per entity (subheading + its fields table),
// used when "Include sub-entities" is on so the whole Sample/Acquisition field
// list reads top-to-bottom like the TOML structure.
export function GroupedFields({
  groups
}: {
  readonly groups: { entity: SchemaEntity; fields: SchemaField[] }[];
}) {
  return (
    <Stack spacing={2}>
      {groups.map(({ entity, fields }) => (
        <Box key={entity.id}>
          <Typography
            component="h4"
            sx={{ fontWeight: 600, mb: 0.5 }}
            variant="subtitle1"
          >
            {entity.name}
          </Typography>
          <FieldsTable fields={fields} />
        </Box>
      ))}
    </Stack>
  );
}

// Chips describing an entity's gating + cardinality — shared by both variants.
export function EntityMeta({ entity }: { readonly entity: SchemaEntity }) {
  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{ flexWrap: 'wrap', alignItems: 'center' }}
    >
      <Chip label={entity.cardinality} size="small" />
      {entity.arm ? (
        <Chip
          color="secondary"
          label={entity.arm}
          size="small"
          variant="outlined"
        />
      ) : null}
      {entity.chromatinOnly ? (
        <Chip
          color="secondary"
          label="chromatin only"
          size="small"
          variant="outlined"
        />
      ) : null}
    </Stack>
  );
}

export function SchemaControls({
  value,
  onChange
}: {
  readonly value: Controls;
  readonly onChange: (c: Controls) => void;
}) {
  return (
    <Stack
      direction="row"
      spacing={3}
      sx={{
        flexWrap: 'wrap',
        rowGap: 2,
        p: 2,
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        bgcolor: 'background.paper',
        position: 'sticky',
        top: 0,
        zIndex: 1
      }}
    >
      <ControlGroup label="Data source">
        <ToggleButtonGroup
          exclusive
          onChange={(_e, arm) => arm && onChange({ ...value, arm })}
          size="small"
          value={value.arm}
        >
          <ToggleButton value="experimental">Experimental</ToggleButton>
          <ToggleButton value="simulation">Simulation</ToggleButton>
        </ToggleButtonGroup>
      </ControlGroup>

      <ControlGroup label="Project">
        <ToggleButtonGroup
          exclusive
          onChange={(_e, v) =>
            v && onChange({ ...value, chromatin: v === 'chromatin' })
          }
          size="small"
          value={value.chromatin ? 'chromatin' : 'other'}
        >
          <ToggleButton value="chromatin">Chromatin</ToggleButton>
          <ToggleButton value="other">Non-chromatin</ToggleButton>
        </ToggleButtonGroup>
      </ControlGroup>

      <ControlGroup label="Source">
        <ToggleButtonGroup
          exclusive
          onChange={(_e, source) => source && onChange({ ...value, source })}
          size="small"
          value={value.source}
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="authored">Authored</ToggleButton>
          <ToggleButton value="derived">Derived</ToggleButton>
        </ToggleButtonGroup>
      </ControlGroup>
    </Stack>
  );
}

function ControlGroup({
  label,
  children
}: {
  readonly label: string;
  readonly children: React.ReactNode;
}) {
  return (
    <Box>
      <Typography
        color="text.secondary"
        sx={{ display: 'block', mb: 0.5 }}
        variant="caption"
      >
        {label}
      </Typography>
      {children}
    </Box>
  );
}
