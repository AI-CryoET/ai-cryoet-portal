// PROTOTYPE — throwaway. Shared bits both layout variants use: the hybrid
// control bar, the pure filter, the source badge, and the fields table.
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
  Typography,
} from '@mui/material'
import EditNoteIcon from '@mui/icons-material/EditNote'
import SettingsSuggestIcon from '@mui/icons-material/SettingsSuggest'
import type { Arm, SchemaEntity, SchemaField, SourceKind } from './schemaData'

export type SourceFilter = 'all' | 'authored' | 'derived'

export interface Controls {
  arm: Arm
  chromatin: boolean // true = chromatin, false = non-chromatin
  source: SourceFilter
}

// Gate an entity by the arm + project toggles.
function entityVisible(entity: SchemaEntity, c: Controls): boolean {
  if (entity.arm && entity.arm !== c.arm) return false
  if (entity.chromatinOnly && !c.chromatin) return false
  return true
}

function fieldVisible(f: SchemaField, source: SourceFilter): boolean {
  return source === 'all' || f.kind === source
}

// Filter the tree: drop gated entities, filter each entity's fields by source,
// recurse into children, and prune entities with no visible fields or children.
export function filterTree(entities: SchemaEntity[], c: Controls): SchemaEntity[] {
  return entities.flatMap((entity) => {
    if (!entityVisible(entity, c)) return []
    const fields = entity.fields.filter((f) => fieldVisible(f, c.source))
    const children = entity.children ? filterTree(entity.children, c) : undefined
    if (fields.length === 0 && (!children || children.length === 0)) return []
    return [{ ...entity, fields, children }]
  })
}

export function SourceBadge({ source, kind }: { source: string; kind: SourceKind }) {
  const authored = kind === 'authored'
  return (
    <Chip
      size="small"
      variant="outlined"
      color={authored ? 'primary' : 'default'}
      icon={authored ? <EditNoteIcon /> : <SettingsSuggestIcon />}
      label={source}
      sx={{ fontFamily: 'monospace', fontSize: '0.72rem' }}
    />
  )
}

export function FieldsTable({ fields }: { fields: SchemaField[] }) {
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
        {fields.map((f) => (
          <TableRow key={f.field}>
            <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
              {f.field}
            </TableCell>
            <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
              {f.type}
            </TableCell>
            <TableCell>
              <SourceBadge source={f.source} kind={f.kind} />
            </TableCell>
            <TableCell>
              <Typography variant="body2" color="text.secondary">
                {f.notes}
              </Typography>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

// Chips describing an entity's gating + cardinality — shared by both variants.
export function EntityMeta({ entity }: { entity: SchemaEntity }) {
  return (
    <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', alignItems: 'center' }}>
      <Chip size="small" label={entity.cardinality} />
      {entity.arm && <Chip size="small" color="secondary" variant="outlined" label={entity.arm} />}
      {entity.chromatinOnly && (
        <Chip size="small" color="secondary" variant="outlined" label="chromatin only" />
      )}
    </Stack>
  )
}

export function SchemaControls({
  value,
  onChange,
}: {
  value: Controls
  onChange: (c: Controls) => void
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
        zIndex: 1,
      }}
    >
      <ControlGroup label="Data source">
        <ToggleButtonGroup
          exclusive
          size="small"
          value={value.arm}
          onChange={(_e, arm) => arm && onChange({ ...value, arm })}
        >
          <ToggleButton value="experimental">Experimental</ToggleButton>
          <ToggleButton value="simulation">Simulation</ToggleButton>
        </ToggleButtonGroup>
      </ControlGroup>

      <ControlGroup label="Project">
        <ToggleButtonGroup
          exclusive
          size="small"
          value={value.chromatin ? 'chromatin' : 'other'}
          onChange={(_e, v) => v && onChange({ ...value, chromatin: v === 'chromatin' })}
        >
          <ToggleButton value="chromatin">Chromatin</ToggleButton>
          <ToggleButton value="other">Non-chromatin</ToggleButton>
        </ToggleButtonGroup>
      </ControlGroup>

      <ControlGroup label="Source">
        <ToggleButtonGroup
          exclusive
          size="small"
          value={value.source}
          onChange={(_e, source) => source && onChange({ ...value, source })}
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="authored">Authored</ToggleButton>
          <ToggleButton value="derived">Derived</ToggleButton>
        </ToggleButtonGroup>
      </ControlGroup>
    </Stack>
  )
}

function ControlGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
        {label}
      </Typography>
      {children}
    </Box>
  )
}
