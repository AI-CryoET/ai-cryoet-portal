import { createFileRoute } from '@tanstack/react-router'
import { Breadcrumbs, Stack, Typography } from '@mui/material'
import { CustomLink } from '~/components/CustomLink'
import { ScanHistoryTable } from '~/components/manage/ScanHistoryTable'
import { scanRunsQueryOptions, useScanRunsQuery } from '~/utils/queryOptions'

export const Route = createFileRoute('/manage/scans')({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(scanRunsQueryOptions),
  component: ScanHistoryRoute,
})

function ScanHistoryRoute() {
  const { data: runs } = useScanRunsQuery()

  return (
    <Stack spacing={3}>
      <Breadcrumbs aria-label="breadcrumb">
        <CustomLink to="/" color="inherit" sx={{ fontWeight: 700 }}>
          Home
        </CustomLink>
        <CustomLink to="/manage" color="inherit">
          Manage
        </CustomLink>
        <CustomLink to="/manage/warnings" color="inherit">
          Warnings &amp; errors
        </CustomLink>
        <Typography color="text.primary">Scan history</Typography>
      </Breadcrumbs>

      <Typography variant="h5" component="h1">
        Scan history
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Every scan that has run, with its outcome counts. Open a scan to see its
        full log output.
      </Typography>

      <ScanHistoryTable rows={runs} />
    </Stack>
  )
}
