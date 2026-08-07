import { Box, IconButton, Link, Stack, Typography } from '@mui/material';
import GitHubIcon from '@mui/icons-material/GitHub';

// Injected at Docker build time from the shared image version (the `v*.*.*` git
// tag). Unset in dev / local builds — fall back to "dev".
const version = import.meta.env.VITE_APP_VERSION || 'dev';

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
        gap: 2
      }}
    >
      <Stack alignItems="center" direction="row" spacing={1}>
        <Typography variant="body2">v{version}</Typography>
        <IconButton
          aria-label="GitHub repository"
          component="a"
          href="https://github.com/JaneliaSciComp/ai-cryoet"
          rel="noopener noreferrer"
          size="small"
          sx={{ color: 'inherit' }}
          target="_blank"
        >
          <GitHubIcon fontSize="small" />
        </IconButton>
      </Stack>
      <Typography variant="body2">
        <Link
          color="inherit"
          href="https://www.hhmi.org/research/janelia"
          rel="noopener noreferrer"
          target="_blank"
          underline="hover"
        >
          HHMI Janelia Research Campus
        </Link>
      </Typography>
    </Box>
  );
}
