import type { ReactNode } from 'react';
import { Box, Link, Typography } from '@mui/material';
import { ViewAllMetadataButton } from '~/components/common/ViewAllMetadataButton';

// Shared title block for the sample- and acquisition-detail pages: the page
// heading with the "View all metadata" button, an optional warnings link, and
// optional descriptive text. The two ViewAllMetadataButton instances handle
// their own responsive placement (beside the title from `md` up, below it
// otherwise).
export function DetailPageHeader({
  title,
  onViewMetadata,
  editLink,
  warning,
  description
}: {
  readonly title: string;
  readonly onViewMetadata: () => void;
  // "Edit …toml" link, rendered directly under the View all metadata button in
  // both placements (beside the title from `md` up, below it otherwise).
  readonly editLink?: ReactNode;
  // Warnings banner shown under the title when the entity has metadata
  // warnings; omitted otherwise.
  readonly warning?: { href: string; text: string } | null;
  // Optional descriptive text under the title (used on the sample view).
  readonly description?: ReactNode;
}) {
  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 2
        }}
      >
        <Typography component="h1" gutterBottom variant="h5">
          {title}
        </Typography>
        {/* Title-row column (md up): button with the edit link under it. */}
        <Box
          sx={{
            flexShrink: 0,
            display: { xs: 'none', md: 'flex' },
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 1
          }}
        >
          <ViewAllMetadataButton onClick={onViewMetadata} placement="title" />
          {editLink}
        </Box>
      </Box>

      {warning ? (
        <Link fontWeight={700} href={warning.href} variant="body2">
          {warning.text}
        </Link>
      ) : null}

      {description ? (
        <Typography
          color="text.secondary"
          sx={{ mt: warning ? 1 : 0 }}
          variant="body1"
        >
          {description}
        </Typography>
      ) : null}

      {/* Below-title stack (below md): same button + edit link, on their own
          lines under the title/warnings. */}
      <Box sx={{ display: { xs: 'block', md: 'none' } }}>
        <ViewAllMetadataButton onClick={onViewMetadata} placement="below" />
        {editLink ? <Box sx={{ mt: 1 }}>{editLink}</Box> : null}
      </Box>
    </Box>
  );
}
