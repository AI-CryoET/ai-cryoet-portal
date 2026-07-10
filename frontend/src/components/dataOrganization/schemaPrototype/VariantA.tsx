// PROTOTYPE — throwaway. Variant A: accordion of top-level entities, each with
// its fields table; sub-entities indented beneath with a guide line (file-tree
// motif). Scan top-to-bottom; nesting shown by indentation + cardinality chips.
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Stack,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import type { SchemaEntity } from './schemaData'
import { EntityMeta, FieldsTable } from './shared'

function SubEntity({ entity }: { entity: SchemaEntity }) {
  return (
    <Box sx={{ ml: 1.5, pl: 2, borderLeft: 2, borderColor: 'divider' }}>
      <Stack spacing={1} sx={{ mt: 2 }}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'baseline', flexWrap: 'wrap' }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            {entity.name}
          </Typography>
          <EntityMeta entity={entity} />
        </Stack>
        {entity.fields.length > 0 && <FieldsTable fields={entity.fields} />}
        {entity.children?.map((c) => (
          <SubEntity key={c.id} entity={c} />
        ))}
      </Stack>
    </Box>
  )
}

export function VariantA({ tree }: { tree: SchemaEntity[] }) {
  return (
    <Stack spacing={1.5}>
      {tree.map((entity) => (
        <Accordion key={entity.id} defaultExpanded disableGutters>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
              <Typography variant="h6" component="h3">
                {entity.name}
              </Typography>
              <EntityMeta entity={entity} />
            </Stack>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={1}>
              {entity.fields.length > 0 && <FieldsTable fields={entity.fields} />}
              {entity.children?.map((c) => (
                <SubEntity key={c.id} entity={c} />
              ))}
            </Stack>
          </AccordionDetails>
        </Accordion>
      ))}
    </Stack>
  )
}
