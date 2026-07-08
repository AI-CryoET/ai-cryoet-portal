import { createFileRoute } from '@tanstack/react-router'
import { Breadcrumbs, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { DeletionsTable } from '~/components/manage/DeletionsTable'
import { deletionsQueryOptions } from '~/utils/queryOptions'

export const Route = createFileRoute('/manage/deletions')({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(deletionsQueryOptions()),
  component: DeletionsRoute,
})

function DeletionsRoute() {
  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <CustomLink to="/manage" color="inherit">
          Manage
        </CustomLink>
        <Typography color="text.primary">Deletions & renames</Typography>
      </Breadcrumbs>

      <Typography variant="h5" component="h1">
        Deletions & renames
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Append-only audit feed of every sample, acquisition, or child entity a
        scan detected as disappeared or renamed on disk.
      </Typography>

      <DeletionsTable />
    </Stack>
  )
}
