import { useMemo } from 'react';
import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import ScheduleIcon from '@mui/icons-material/Schedule';
import { CronExpressionParser } from 'cron-parser';
import cronstrue from 'cronstrue';
import type { ManageLatestScan, ManageSummary } from '~/types';

// Scan timestamps are Unix seconds; render in the viewer's locale.
function formatTs(seconds: number | null | undefined): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleString(undefined, {
    timeZoneName: 'short'
  });
}

// Map the scan status onto a brand-themed chip colour.
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

function Field({
  label,
  children
}: {
  readonly label: string;
  readonly children: React.ReactNode;
}) {
  return (
    <Box sx={{ minWidth: 150 }}>
      <Typography
        sx={{
          textTransform: 'uppercase',
          letterSpacing: '.05em',
          color: 'text.secondary',
          display: 'block'
        }}
        variant="caption"
      >
        {label}
      </Typography>
      <Box sx={{ mt: 0.5 }}>{children}</Box>
    </Box>
  );
}

// Compute "Every hour · next ≈ HH:MM" from the cron expression. The cron fires
// in the cluster timezone (`cadence_tz`), but the next-fire instant it returns
// is absolute, so we render it in the user's LOCAL time (plan §3.4). Returns
// null when the expression can't be parsed.
function useCadence(
  cron: string,
  tz: string
): { human: string; nextLocal: string } | null {
  return useMemo(() => {
    try {
      const human = cronstrue.toString(cron, { verbose: false });
      const interval = CronExpressionParser.parse(cron, {
        currentDate: new Date(),
        tz
      });
      const next = interval.next().toDate();
      const nextLocal = next.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short'
      });
      return { human, nextLocal };
    } catch {
      return null;
    }
  }, [cron, tz]);
}

function LastScanFields({ scan }: { readonly scan: ManageLatestScan }) {
  return (
    <Stack direction="row" flexWrap="wrap" spacing={4} useFlexGap>
      <Field label="Last scan started">
        <Typography sx={{ fontWeight: 600 }} variant="body2">
          {formatTs(scan.started_at)}
        </Typography>
      </Field>
      <Field label="Last scan ended">
        <Typography sx={{ fontWeight: 600 }} variant="body2">
          {formatTs(scan.ended_at)}
        </Typography>
      </Field>
      <Field label="Status">
        <Chip
          color={statusColor(scan.status)}
          label={scan.status}
          size="small"
          variant="outlined"
        />
      </Field>
    </Stack>
  );
}

export function StatusCadenceCard({
  summary
}: {
  readonly summary: ManageSummary;
}) {
  const cadence = useCadence(summary.cadence_cron, summary.cadence_tz);
  const { latest_scan } = summary;

  return (
    <Stack spacing={2}>
      <Stack
        alignItems="stretch"
        direction="row"
        flexWrap="wrap"
        spacing={2}
        useFlexGap
      >
        <Paper sx={{ px: 2.5, py: 2, borderRadius: 2 }} variant="outlined">
          {latest_scan ? (
            <LastScanFields scan={latest_scan} />
          ) : (
            <Typography color="text.secondary" variant="body2">
              No completed scans yet.
            </Typography>
          )}
        </Paper>

        <Paper sx={{ px: 2.5, py: 2, borderRadius: 2 }} variant="outlined">
          <Stack alignItems="center" direction="row" spacing={1.5}>
            <ScheduleIcon color="action" />
            <Field label="Scan cadence">
              <Typography sx={{ fontWeight: 600 }} variant="body2">
                {cadence
                  ? `${cadence.human} · next ≈ ${cadence.nextLocal}`
                  : summary.cadence_cron}
              </Typography>
            </Field>
          </Stack>
        </Paper>
      </Stack>

      <Typography color="text.secondary" variant="body2">
        Edited a{' '}
        <Box
          component="code"
          sx={{
            fontFamily: 'monospace',
            bgcolor: 'action.hover',
            px: 0.5,
            borderRadius: 0.5
          }}
        >
          .toml
        </Box>{' '}
        after the last scan? Your change will appear after the next scan
        {cadence ? ` (~${cadence.nextLocal}).` : '.'}
      </Typography>
    </Stack>
  );
}
