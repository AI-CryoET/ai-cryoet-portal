// PROTOTYPE — throwaway. Hosts the two layout variants on the Data schema tab:
// shared control bar + filtering, then the active variant, plus the floating
// switcher. Once a layout wins, fold it into the real page and delete the rest.
import { useMemo, useState } from 'react'
import { Box, Stack, Typography } from '@mui/material'
import { SCHEMA } from './schemaData'
import { filterTree, SchemaControls, type Controls } from './shared'
import { VariantA } from './VariantA'
import { VariantC } from './VariantC'
import { PrototypeSwitcher, type VariantDef } from './PrototypeSwitcher'

const VARIANTS: VariantDef[] = [
  { key: 'A', name: 'Accordion + field tables' },
  { key: 'C', name: 'Tree + two-pane' },
]

export function SchemaExplorer({
  variant,
  onVariantChange,
}: {
  variant: string
  onVariantChange: (key: string) => void
}) {
  const [controls, setControls] = useState<Controls>({
    arm: 'experimental',
    chromatin: true,
    source: 'all',
  })
  const tree = useMemo(() => filterTree(SCHEMA, controls), [controls])

  return (
    <>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h5" component="h1">
            Data schema
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Every field stored in the catalog, by entity. Toggle the arm and
            project to see which entities apply, and filter by whether a field is
            authored in a TOML file or derived by the scanner.
          </Typography>
        </Box>
        <SchemaControls value={controls} onChange={setControls} />
        {variant === 'C' ? <VariantC tree={tree} /> : <VariantA tree={tree} />}
      </Stack>
      <PrototypeSwitcher variants={VARIANTS} current={variant} onSelect={onVariantChange} />
    </>
  )
}
