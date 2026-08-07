import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Typography
} from '@mui/material';
import type { ReactNode } from 'react';

type Props = {
  readonly title: string;
  readonly children: ReactNode;
};

// Top-level collapsible wrapper for a whole property section ("Sample
// properties" / "Acquisition properties"). Expanded by default.
export function FilterSection({ title, children }: Props) {
  return (
    <Accordion
      defaultExpanded
      disableGutters
      elevation={0}
      square
      sx={{
        '&:before': { display: 'none' },
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.5 }}>
        <Typography variant="h6">{title}</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 1.5 }}>{children}</AccordionDetails>
    </Accordion>
  );
}
