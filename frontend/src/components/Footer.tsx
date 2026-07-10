import { Box, IconButton, Link, Stack, Typography } from '@mui/material'
import GitHubIcon from '@mui/icons-material/GitHub'

// Injected at Docker build time from the shared image version (the `v*.*.*` git
// tag). Unset in dev / local builds — fall back to "dev".
const version = import.meta.env.VITE_APP_VERSION || 'dev'

export function Footer() {
  return (
    <Box
      component="footer"
      sx={{
        bgcolor: 'primary.main',
        color: 'primary.contrastText',
        px: { xs: 2, md: 4 },
        py: 2,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 2,
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="body2">v{version}</Typography>
        <IconButton
          component="a"
          href="https://github.com/JaneliaSciComp/ai-cryoet"
          target="_blank"
          rel="noopener noreferrer"
          size="small"
          aria-label="GitHub repository"
          sx={{ color: 'inherit' }}
        >
          <GitHubIcon fontSize="small" />
        </IconButton>
      </Stack>
      <Typography variant="body2">
        <Link
          href="https://www.hhmi.org/research/janelia"
          color="inherit"
          underline="hover"
          target="_blank"
          rel="noopener noreferrer"
        >
          HHMI Janelia Research Campus
        </Link>
      </Typography>
    </Box>
  )
}
