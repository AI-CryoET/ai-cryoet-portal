import { Box, Stack, Typography } from '@mui/material';
import { ButtonLink } from '~/components/CustomLink';
import { HeroBackdrop } from './HeroBackdrop';

// The portal's front door: a dark banner that mirrors the app's existing
// `primary.dark` styling (StatsBanner, Footer) and routes visitors to the two
// top-level tasks — browsing all data, or managing it (upload, author, review).
// Per-collection browsing (experimental / MD simulation) lives in the header
// nav rather than crowding the hero.
export function LandingHero() {
  return (
    <Box
      sx={{
        position: 'relative',
        overflow: 'hidden',
        // Rendered as a sibling of <Header> (see __root.tsx), so it's already
        // full viewport width and flush under the nav — no full-bleed hacks.
        bgcolor: 'primary.dark',
        color: 'common.white',
        px: { xs: 3, md: 6 },
        py: { xs: 5, md: 7 },
        textAlign: 'center'
      }}
    >
      <HeroBackdrop />
      <Box
        sx={theme => ({
          // Keep the text/buttons readable and aligned with the page content
          // below, while the background spans edge to edge.
          position: 'relative',
          zIndex: 1,
          maxWidth: theme.breakpoints.values.lg,
          mx: 'auto'
        })}
      >
        <Typography
          color="secondary.main"
          component="h1"
          gutterBottom
          variant="h3"
        >
          AI+CryoET Data Portal
        </Typography>
        <Typography
          color="inherit"
          component="p"
          sx={{ opacity: 0.85, mb: 4 }}
          variant="h6"
        >
          Track, explore, and visualize data collected for the AI+CryoET project
        </Typography>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          justifyContent="center"
          spacing={2}
        >
          <ButtonLink
            size="large"
            sx={{
              bgcolor: 'common.white',
              color: 'primary.dark',
              '&:hover': { bgcolor: 'grey.200' }
            }}
            to="/data"
            variant="contained"
          >
            Explore Data
          </ButtonLink>
          <ButtonLink
            size="large"
            sx={{
              bgcolor: 'common.white',
              color: 'primary.dark',
              '&:hover': { bgcolor: 'grey.200' }
            }}
            to="/manage"
            variant="contained"
          >
            Manage Data
          </ButtonLink>
        </Stack>
      </Box>
    </Box>
  );
}
