import type { ReactNode } from 'react'
import { Box, Link, Typography } from '@mui/material'
import { ViewAllMetadataButton } from '~/components/common/ViewAllMetadataButton'

// Shared title block for the sample- and acquisition-detail pages: the page
// heading with the "View all metadata" button, an optional warnings link, and
// optional descriptive text. The two ViewAllMetadataButton instances handle
// their own responsive placement (beside the title from `md` up, below it
// otherwise).
export function DetailPageHeader(props: {
  title: string
  onViewMetadata: () => void
  // "Edit …toml" link, rendered directly under the View all metadata button in
  // both placements (beside the title from `md` up, below it otherwise).
  editLink?: ReactNode
  // Warnings banner shown under the title when the entity has metadata
  // warnings; omitted otherwise.
  warning?: { href: string; text: string } | null
  // Optional descriptive text under the title (used on the sample view).
  description?: ReactNode
}) {
  const { title, onViewMetadata, editLink, warning, description } = props
  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 2,
        }}
      >
        <Typography variant="h5" component="h1" gutterBottom>
          {title}
        </Typography>
        {/* Title-row column (md up): button with the edit link under it. */}
        <Box
          sx={{
            flexShrink: 0,
            display: { xs: 'none', md: 'flex' },
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 1,
          }}
        >
          <ViewAllMetadataButton placement="title" onClick={onViewMetadata} />
          {editLink}
        </Box>
      </Box>

      {warning ? (
        <Link href={warning.href} variant="body2" fontWeight={700}>
          {warning.text}
        </Link>
      ) : null}

      {description ? (
        <Typography
          variant="body1"
          color="text.secondary"
          sx={{ mt: warning ? 1 : 0 }}
        >
          {description}
        </Typography>
      ) : null}

      {/* Below-title stack (below md): same button + edit link, on their own
          lines under the title/warnings. */}
      <Box sx={{ display: { xs: 'block', md: 'none' } }}>
        <ViewAllMetadataButton placement="below" onClick={onViewMetadata} />
        {editLink ? <Box sx={{ mt: 1 }}>{editLink}</Box> : null}
      </Box>
    </Box>
  )
}
