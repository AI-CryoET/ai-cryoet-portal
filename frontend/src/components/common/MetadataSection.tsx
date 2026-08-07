import type { ReactNode, SyntheticEvent } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Typography
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

export type MetadataRow = { label: string; value: ReactNode };

export type MetadataSectionData = {
  readonly title: string;
  readonly rows: MetadataRow[];
  readonly defaultExpanded?: boolean;
};

// Placeholder shown for fields that exist in the schema but aren't filled in
// for this entity, so every applicable field stays visible.
const EMPTY = '—';

function isEmpty(value: ReactNode): boolean {
  return value == null || value === '';
}

// One collapsible metadata section: a titled accordion wrapping a two-column
// label/value table. Every row is rendered — empty values show a placeholder
// rather than being hidden — so callers pass the full field list for the
// section. Sections that don't apply to an entity are omitted by the builder.
//
// Pass `expanded`/`onChange` to drive the accordion from a parent (e.g. an
// "Expand all" control); otherwise it manages its own state via
// `defaultExpanded`.
export function MetadataSection({
  title,
  rows,
  defaultExpanded,
  expanded,
  onChange
}: MetadataSectionData & {
  readonly expanded?: boolean;
  readonly onChange?: (value: boolean) => void;
}) {
  if (rows.length === 0) {
    return null;
  }

  const controlled = expanded !== undefined;

  return (
    <Accordion
      {...(controlled
        ? {
            expanded,
            onChange: (_e: SyntheticEvent, isExpanded: boolean) =>
              onChange?.(isExpanded)
          }
        : { defaultExpanded })}
      disableGutters
      elevation={0}
      sx={{
        border: 1,
        borderColor: 'divider',
        borderRadius: 2,
        overflow: 'hidden',
        '&:before': { display: 'none' }
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography
          sx={{ fontWeight: 700, color: 'primary.main' }}
          variant="subtitle1"
        >
          {title}
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ p: 0 }}>
        <Table size="small">
          <TableBody>
            {rows.map((row, i) => {
              const empty = isEmpty(row.value);
              return (
                <TableRow
                  key={row.label}
                  sx={{
                    bgcolor: i % 2 === 0 ? 'action.hover' : 'transparent',
                    '& td': { borderBottom: 'none' }
                  }}
                >
                  <TableCell
                    sx={{
                      width: '45%',
                      color: 'text.secondary',
                      fontWeight: 600,
                      verticalAlign: 'top'
                    }}
                  >
                    {row.label}
                  </TableCell>
                  <TableCell
                    sx={{
                      verticalAlign: 'top',
                      color: empty ? 'text.disabled' : undefined
                    }}
                  >
                    {empty ? EMPTY : row.value}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </AccordionDetails>
    </Accordion>
  );
}
