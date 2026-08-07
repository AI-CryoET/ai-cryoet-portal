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
  // Whether the group is open, revealing its member properties.
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly disabled?: boolean;
  readonly children: ReactNode;
};

// A collapsible group ("General", "Chromatin", …). Collapsed by default: the
// title's expand button reveals the member FilterProperty rows. Open state is
// owned by FilterPanel.
export function FilterGroup({
  title,
  expanded,
  onToggle,
  disabled,
  children
}: Props) {
  return (
    <Accordion
      disableGutters
      disabled={disabled}
      elevation={0}
      expanded={expanded}
      onChange={onToggle}
      square
      sx={{ '&:before': { display: 'none' }, mb: 1 }}
    >
      <AccordionSummary
        aria-label={`${expanded ? 'Collapse' : 'Expand'} all ${title} filters`}
        expandIcon={<ExpandMoreIcon fontSize="small" />}
        sx={{ px: 1, bgcolor: 'action.hover', borderRadius: 1 }}
      >
        <Typography fontWeight="bold" variant="subtitle2">
          {title}
        </Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 0, pt: 0 }}>{children}</AccordionDetails>
    </Accordion>
  );
}
