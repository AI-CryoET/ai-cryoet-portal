// PROTOTYPE — throwaway. Variant C: two-pane. Left = nesting tree of entities
// (file-tree style, indented, clickable). Right = the selected entity's fields
// table + header. Strong nesting clarity; one entity's fields at a time.
import { useMemo, useState } from 'react'
import { Box, Divider, Stack, Typography } from '@mui/material'
import type { SchemaEntity } from './schemaData'
import { EntityMeta, FieldsTable } from './shared'

// Flatten to (entity, depth, parent) in display order for the left tree +
// lookup. parent lets the right pane show "Sample › Chromatin" for orientation.
type Row = { entity: SchemaEntity; depth: number; parent: SchemaEntity | null }
function flatten(entities: SchemaEntity[], depth = 0, parent: SchemaEntity | null = null): Row[] {
  return entities.flatMap((entity) => [
    { entity, depth, parent },
    ...(entity.children ? flatten(entity.children, depth + 1, entity) : []),
  ])
}

export function VariantC({ tree }: { tree: SchemaEntity[] }) {
  const rows = useMemo(() => flatten(tree), [tree])
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // Keep selection valid as filters change; fall back to the first entity.
  const selectedRow = rows.find((r) => r.entity.id === selectedId) ?? rows[0] ?? null
  const selected = selectedRow?.entity ?? null
  const parent = selectedRow?.parent ?? null

  return (
    <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ alignItems: 'flex-start' }}>
      <Box
        sx={{
          flex: '0 0 240px',
          alignSelf: 'stretch',
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
          p: 1,
          position: { md: 'sticky' },
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
  )
}
