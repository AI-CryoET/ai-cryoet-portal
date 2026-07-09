import { createFileRoute } from '@tanstack/react-router'
import { Box, Breadcrumbs, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { AuthoringForm } from '~/components/authoring/AuthoringForm'

type AuthorSampleSearch = { id?: string }

export const Route = createFileRoute('/author/sample')({
  // Deep-link auto-load: `/author/sample?id=<sampleId>` pulls that sample from
  // the API and seeds the form (ADR-0004 + the "Edit sample.toml" link).
  validateSearch: (search: Record<string, unknown>): AuthorSampleSearch => ({
    id: typeof search.id === 'string' && search.id ? search.id : undefined,
  }),
  component: AuthorSampleRoute,
})

function AuthorSampleRoute() {
  const { id } = Route.useSearch()
  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <Typography color="text.primary">Author sample</Typography>
      </Breadcrumbs>

      <Box>
        <Typography variant="h5" component="h1">
          Author <code>sample.toml</code>
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Fill the sample's fields and download a clean value-only file.
        </Typography>
      </Box>

      <AuthoringForm form="sample" initialId={id} />
    </Stack>
  )
}
