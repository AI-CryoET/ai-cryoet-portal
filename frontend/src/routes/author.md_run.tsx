import { createFileRoute } from '@tanstack/react-router'
import { Box, Breadcrumbs, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { AuthoringForm } from '~/components/authoring/AuthoringForm'

export const Route = createFileRoute('/author/md_run')({
  component: AuthorMdRunRoute,
})

function AuthorMdRunRoute() {
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

      <AuthoringForm form="md_run" />
    </Stack>
  )
}
