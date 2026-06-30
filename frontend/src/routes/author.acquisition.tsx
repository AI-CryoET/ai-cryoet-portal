import { createFileRoute } from '@tanstack/react-router'
import { Box, Breadcrumbs, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { AuthoringForm } from '~/components/authoring/AuthoringForm'

export const Route = createFileRoute('/author/acquisition')({
  // Edit links carry the composite identity (?id=…&sampleId=…) so the form can
  // auto-load the right acquisition.
  validateSearch: (search: Record<string, unknown>) => ({
    id: typeof search.id === 'string' ? search.id : undefined,
    sampleId: typeof search.sampleId === 'string' ? search.sampleId : undefined,
  }),
  component: AuthorAcquisitionRoute,
})

function AuthorAcquisitionRoute() {
  const { id, sampleId } = Route.useSearch()
  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <Typography color="text.primary">Author acquisition</Typography>
      </Breadcrumbs>

      <Box>
        <Typography variant="h5" component="h1">
          Author <code>acquisition.toml</code>
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Fill the acquisition's fields and download a clean value-only file.
        </Typography>
      </Box>

      <AuthoringForm
        form="acquisition"
        initialId={id}
        initialSampleId={sampleId}
      />
    </Stack>
  )
}
