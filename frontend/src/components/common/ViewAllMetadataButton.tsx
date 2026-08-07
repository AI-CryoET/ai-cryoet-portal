import { Box, Button } from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

// The button lives in two spots and only one shows at a time: in the page
// title row from the `md` breakpoint up, and below the title/warnings below it
// (where it would otherwise crowd or overflow the heading). Both are rendered;
// the `display` breakpoints pick which is visible.
export function ViewAllMetadataButton({
  onClick,
  placement
}: {
  readonly onClick: () => void;
  readonly placement: 'title' | 'below';
}) {
  const button = (
    <Button
      onClick={onClick}
      size="small"
      startIcon={<InfoOutlinedIcon />}
      variant="contained"
    >
      View all metadata
    </Button>
  );

  // Title-row instance: only shown from `md` up.
  if (placement === 'title') {
    return (
      <Box sx={{ flexShrink: 0, display: { xs: 'none', md: 'inline-flex' } }}>
        {button}
      </Box>
    );
  }

  // Below-title instance (below `md`): a block wrapper puts it on its own line
  // (a bare Button is inline-flex and would tuck in beside the inline warning
  // text).
  return (
    <Box sx={{ mt: 2, display: { xs: 'block', md: 'none' } }}>{button}</Box>
  );
}
