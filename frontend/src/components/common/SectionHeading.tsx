import type { ReactNode } from 'react';
import { Box, Typography } from '@mui/material';

// Shared section header used above the tables on the detail pages: an
// `action.hover` band with an `h6` heading.
export function SectionHeading(props: { readonly children: ReactNode }) {
  return (
    <Box
      sx={{ bgcolor: 'action.hover', borderRadius: 2, px: 2, py: 1.25, mb: 2 }}
    >
      <Typography component="h2" variant="h6">
        {props.children}
      </Typography>
    </Box>
  );
}
