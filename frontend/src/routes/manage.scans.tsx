import { createFileRoute } from '@tanstack/react-router';
import { Breadcrumbs, Stack, Typography } from '@mui/material';
import { CustomLink } from '~/components/CustomLink';
import { ScanHistoryTable } from '~/components/manage/ScanHistoryTable';
import { scanRunsQueryOptions, useScanRunsQuery } from '~/utils/queryOptions';

export const Route = createFileRoute('/manage/scans')({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(scanRunsQueryOptions),
  component: ScanHistoryRoute
});

function ScanHistoryRoute() {
  const { data: runs } = useScanRunsQuery();

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink color="inherit" sx={{ fontWeight: 700 }} to="/">
          Home
        </CustomLink>
        <CustomLink color="inherit" to="/manage">
          Manage
        </CustomLink>
        <CustomLink color="inherit" to="/manage/warnings">
          Warnings &amp; errors
        </CustomLink>
        <Typography color="text.primary">Scan history</Typography>
      </Breadcrumbs>

      <Typography component="h1" variant="h5">
        Scan history
      </Typography>
      <Typography color="text.secondary" variant="body2">
        Every scan that has run, with its outcome counts. Open a scan to see its
        full log output.
      </Typography>

      <ScanHistoryTable rows={runs} />
    </Stack>
  );
}
