import { createFileRoute, notFound } from '@tanstack/react-router';
import {
  Box,
  Breadcrumbs,
  Chip,
  Paper,
  Stack,
  Typography
} from '@mui/material';
import { CustomLink } from '~/components/CustomLink';
import { SectionHeader } from '~/components/manage/SectionHeader';
import { RunLogPanel } from '~/components/manage/RunLogPanel';
import { scanRunQueryOptions, useScanRunQuery } from '~/utils/queryOptions';
import type { ScanRun } from '~/types';

export const Route = createFileRoute('/manage/scans_/$scanId')({
  loader: async ({ context: { queryClient }, params: { scanId } }) => {
    // The scan must exist; an unknown id 404s, which we surface as notFound.
    try {
      await queryClient.ensureQueryData(scanRunQueryOptions(scanId));
    } catch (err) {
      if (err instanceof Error && err.message.includes('404')) {
        throw notFound();
      }
      throw err;
    }
  },
  component: ScanRunDetailRoute
});

// Scan timestamps are Unix seconds; render in the viewer's locale.
function formatTs(seconds: number | null): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleString(undefined, {
    timeZoneName: 'short'
  });
}

function statusColor(
  status: string
): 'success' | 'error' | 'warning' | 'default' {
  switch (status) {
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    case 'running':
      return 'warning';
    default:
      return 'default';
  }
}

const count = (v: number | null) => (v == null ? '—' : v.toLocaleString());

function Field({
  label,
  value
}: {
  readonly label: string;
  readonly value: React.ReactNode;
}) {
  return (
    <Stack spacing={0.5} sx={{ minWidth: 120 }}>
      <Typography
        sx={{ textTransform: 'uppercase', color: 'text.secondary' }}
        variant="caption"
      >
        {label}
      </Typography>
      <Typography sx={{ fontWeight: 600 }} variant="body2">
        {value}
      </Typography>
    </Stack>
  );
}

function RunSummaryCard({ run }: { readonly run: ScanRun }) {
  return (
    <Paper sx={{ px: 2.5, py: 2, borderRadius: 2 }} variant="outlined">
      <Stack direction="row" flexWrap="wrap" spacing={4} useFlexGap>
        <Field label="Started" value={formatTs(run.started_at)} />
        <Field label="Ended" value={formatTs(run.ended_at)} />
        <Field
          label="Status"
          value={
            <Chip
              color={statusColor(run.status)}
              label={run.status}
              size="small"
              variant="outlined"
            />
          }
        />
        <Field label="Updated" value={count(run.n_upserted)} />
        <Field label="Skipped" value={count(run.n_skipped)} />
        <Field label="Failed" value={count(run.n_failed)} />
        <Field label="New issues" value={count(run.n_new_issues)} />
        <Field label="Resolved issues" value={count(run.n_resolved_issues)} />
      </Stack>
    </Paper>
  );
}

function ScanRunDetailRoute() {
  const { scanId } = Route.useParams();
  const { data: run } = useScanRunQuery(scanId);

  const title = `Scan ${formatTs(run.started_at)}`;

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
        <CustomLink color="inherit" to="/manage/scans">
          Scan history
        </CustomLink>
        <Typography color="text.primary">{title}</Typography>
      </Breadcrumbs>

      <Typography component="h1" variant="h5">
        {title}
      </Typography>

      <RunSummaryCard run={run} />

      <Box>
        <SectionHeader title="Scan log" />
        <Paper sx={{ borderRadius: 2, overflow: 'hidden' }} variant="outlined">
          <RunLogPanel scanId={scanId} />
        </Paper>
      </Box>
    </Stack>
  );
}
