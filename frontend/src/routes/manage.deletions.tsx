import { createFileRoute } from '@tanstack/react-router';
import { Breadcrumbs, Stack, Typography } from '@mui/material';
import { CustomLink } from '~/components/CustomLink';
import { DeletionsTable } from '~/components/manage/DeletionsTable';
import { deletionsQueryOptions } from '~/utils/queryOptions';

export const Route = createFileRoute('/manage/deletions')({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(deletionsQueryOptions()),
  component: DeletionsRoute
});

function DeletionsRoute() {
  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink color="inherit" sx={{ fontWeight: 700 }} to="/">
          Home
        </CustomLink>
        <CustomLink color="inherit" to="/manage">
          Manage
        </CustomLink>
        <Typography color="text.primary">Deletions & renames</Typography>
      </Breadcrumbs>

      <Typography component="h1" variant="h5">
        Deletions & renames
      </Typography>
      <Typography color="text.secondary" variant="body2">
        Append-only audit feed of every sample, acquisition, or child entity a
        scan detected as disappeared or renamed on disk.
      </Typography>

      <DeletionsTable />
    </Stack>
  );
}
