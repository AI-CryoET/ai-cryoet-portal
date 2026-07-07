import { createFileRoute } from '@tanstack/react-router'
import { Box, Breadcrumbs, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { AuthoringForm } from '~/components/authoring/AuthoringForm'

type AuthorMdRunSearch = { id?: string }

export const Route = createFileRoute('/author/md_run')({
  // Deep-link auto-load: `/author/md_run?id=<mdRunId>` pulls that run from
  // the API and seeds the form (ADR-0004 + the manage-page warning-row link).
  validateSearch: (search: Record<string, unknown>): AuthorMdRunSearch => ({
    id: typeof search.id === 'string' && search.id ? search.id : undefined,
  }),
  component: AuthorMdRunRoute,
})

function AuthorMdRunRoute() {
  const { id } = Route.useSearch()
  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <Typography color="text.primary">Author MD run</Typography>
      </Breadcrumbs>

      <Box>
        <Typography variant="h5" component="h1">
          Author <code>md_run.toml</code>
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Fill the run's fields and download a clean value-only file.
        </Typography>
      </Box>

      <AuthoringForm form="md_run" initialId={id} />
    </Stack>
  )
}
