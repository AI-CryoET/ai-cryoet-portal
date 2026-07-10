// Real schema explorer: tree of entities on the left, selected entity's
// fields table on the right (with the parent entity shown as an overline
// above the title for orientation). Owns its own filter state.
import { useMemo, useState } from 'react'
import { Box, Divider, Stack, Typography } from '@mui/material'
import { SCHEMA, type SchemaEntity } from './schemaData'
import { EntityMeta, FieldsTable, filterTree, SchemaControls, type Controls } from './shared'

// Flatten to (entity, depth, parent) in display order for the left tree +
// lookup. parent lets the right pane show "Sample › Chromatin" for orientation.
type Row = { entity: SchemaEntity; depth: number; parent: SchemaEntity | null }
function flatten(entities: SchemaEntity[], depth = 0, parent: SchemaEntity | null = null): Row[] {
  return entities.flatMap((entity) => [
    { entity, depth, parent },
    ...(entity.children ? flatten(entity.children, depth + 1, entity) : []),
  ])
}

export function SchemaExplorer() {
  const [controls, setControls] = useState<Controls>({
    arm: 'experimental',
    chromatin: true,
    source: 'all',
  })
  const tree = useMemo(() => filterTree(SCHEMA, controls), [controls])
  const rows = useMemo(() => flatten(tree), [tree])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // Keep selection valid as filters change; fall back to the first entity.
  const selectedRow = rows.find((r) => r.entity.id === selectedId) ?? rows[0] ?? null
  const selected = selectedRow?.entity ?? null
  const parent = selectedRow?.parent ?? null

  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h5" component="h1">
          Data schema
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Every field stored in the catalog, by entity. Toggle the data source and
          project to see which entities apply, and filter by whether a field is
          authored in a TOML file or derived by the file scanner; for example, data extracted from folder names, MDOC files, or MRC file headers.
        </Typography>
      </Box>
      <SchemaControls value={controls} onChange={setControls} />
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: 'flex-start' }}>
        <Box
          sx={{
            flex: '0 0 240px',
            // Natural height only — don't stretch to match a taller right pane.
            border: 1,
            borderColor: 'divider',
            borderRadius: 1,
            p: 1,
            position: { md: 'sticky' },
            // Offset below the sticky control bar (shared.tsx uses top: 0).
            top: { md: 96 },
          }}
        >
          {rows.map(({ entity, depth }) => {
            const active = selected?.id === entity.id
            return (
              <Box
                key={entity.id}
                component="button"
                onClick={() => setSelectedId(entity.id)}
                sx={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  border: 0,
                  borderLeft: depth > 0 ? 2 : 0,
                  borderColor: 'divider',
                  cursor: 'pointer',
                  bgcolor: active ? 'action.selected' : 'transparent',
                  borderRadius: 0.5,
                  pl: 1 + depth * 1.5,
                  py: 0.5,
                  font: 'inherit',
                  fontWeight: active ? 700 : 400,
                  '&:hover': { bgcolor: 'action.hover' },
                }}
              >
                {entity.name}
              </Box>
            )
          })}
        </Box>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          {selected ? (
            <Stack spacing={1.5}>
              <Box>
                {parent && (
                  <Typography
                    variant="overline"
                    color="text.secondary"
                    sx={{ display: 'block', lineHeight: 1.4 }}
                  >
                    {parent.name}
                  </Typography>
                )}
                <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                  <Typography variant="h6" component="h3">
                    {selected.name}
                  </Typography>
                  <EntityMeta entity={selected} />
                </Stack>
              </Box>
              <Divider />
              {selected.fields.length > 0 ? (
                <FieldsTable fields={selected.fields} />
              ) : (
                <Typography variant="body2" color="text.secondary">
                  No fields match the current source filter.
                </Typography>
              )}
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">
              Nothing matches the current filters.
            </Typography>
          )}
        </Box>
      </Stack>
    </Stack>
  )
}
