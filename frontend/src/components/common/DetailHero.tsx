import type { ReactNode } from 'react';
import { Box } from '@mui/material';

// Shared two-column hero used on the sample- and acquisition-detail pages: a
// thumbnail on the left and path / summary details on the right. Flex (not MUI
// Grid) so the columns sit flush with the page title, `minWidth: 0` lets long
// paths wrap instead of overflowing to the right, and the columns wrap to a
// single column once the viewport is too narrow to fit both.
export function DetailHero(props: {
  readonly thumbnail: ReactNode;
  readonly details: ReactNode;
}) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: { xs: 3, md: 4 },
        alignItems: 'flex-start'
      }}
    >
      <Box sx={{ flex: '1 1 240px', minWidth: 0 }}>{props.thumbnail}</Box>
      <Box sx={{ flex: '2 1 320px', minWidth: 0 }}>{props.details}</Box>
    </Box>
  );
}
