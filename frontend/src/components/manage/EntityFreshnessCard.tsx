import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import type { AcquisitionScanStatus, EntityScanStatus } from '~/types';

// Scan timestamps are Unix seconds; render in the viewer's locale.
function formatTs(seconds: number | null | undefined): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleString(undefined, {
    timeZoneName: 'short'
  });
}

function outcomeColor(
  outcome: EntityScanStatus['last_outcome']
): 'success' | 'error' | 'default' {
  switch (outcome) {
    case 'upserted':
      return 'success';
    case 'failed':
      return 'error';
    default:
      return 'default';
  }
}

function outcomeLabel(outcome: EntityScanStatus['last_outcome']): string {
  return outcome === 'upserted' ? 'updated' : outcome;
}

function Row({
  label,
  children
}: {
  readonly label: string;
  readonly children: React.ReactNode;
}) {
  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 3,
        minWidth: 0
      }}
    >
      <Typography color="text.secondary" variant="body2">
        {label}
      </Typography>
      <Box sx={{ minWidth: 0, textAlign: 'right' }}>{children}</Box>
    </Box>
  );
}

// Thumbnail provenance block — acquisition-only. `missing_source` /
// `render_failed` / a never-generated thumbnail drive the "no preview source"
// and "never" states (plan §4.5, wireframe).
function ThumbnailProvenance({
  status
}: {
  readonly status: AcquisitionScanStatus;
}) {
  const noSource =
    status.thumbnail_status === 'missing_source' ||
    status.thumbnail_source_kind === 'none' ||
    status.thumbnail_source_kind == null;
  const failed = status.thumbnail_status === 'render_failed';

  return (
    <>
      <Row label="Thumbnail source file">
        {noSource ? (
          <Typography sx={{ color: 'warning.main' }} variant="body2">
            — no preview source found —
          </Typography>
        ) : failed ? (
          <Typography sx={{ color: 'error.main' }} variant="body2">
            render failed
          </Typography>
        ) : status.thumbnail_source_path ? (
          <Typography
            sx={{
              fontFamily: 'monospace',
              fontSize: 12.5,
              wordBreak: 'break-all'
            }}
            variant="body2"
          >
            {status.thumbnail_source_path}
          </Typography>
        ) : (
          <Typography color="text.disabled" variant="body2">
            —
          </Typography>
        )}
      </Row>
      <Row label="Thumbnail generated">
        {status.thumbnail_generated_at == null ? (
          <Typography sx={{ color: 'warning.main' }} variant="body2">
            never
          </Typography>
        ) : (
          <Typography variant="body2">
            {formatTs(status.thumbnail_generated_at)}
          </Typography>
        )}
      </Row>
    </>
  );
}

// Priority 2 readout on the sample / acquisition detail pages (plan §1.6, §5.2).
// A not-yet-rescanned entity has `status === null`.
export function EntityFreshnessCard({
  status,
  kind
}: {
  readonly status: EntityScanStatus | AcquisitionScanStatus | null;
  readonly kind: 'sample' | 'acquisition';
}) {
  return (
    <Paper
      elevation={0}
      sx={{ px: 2.5, py: 2, borderRadius: 2, bgcolor: 'grey.100' }}
    >
      <Typography gutterBottom variant="subtitle2">
        Data freshness &amp; preview
      </Typography>
      {status == null ? (
        <Typography color="text.secondary" variant="body2">
          This {kind} has not been scanned yet.
        </Typography>
      ) : (
        <Stack spacing={0.5}>
          <Row label="Last scan outcome">
            <Chip
              color={outcomeColor(status.last_outcome)}
              label={outcomeLabel(status.last_outcome)}
              size="small"
              variant="outlined"
            />
          </Row>
          <Row label="Last updated">
            <Typography variant="body2">
              {formatTs(status.last_changed_at)}
            </Typography>
          </Row>
          <Row label="Last scanned">
            <Typography variant="body2">
              {formatTs(status.last_scanned_at)}
            </Typography>
          </Row>
          {kind === 'acquisition' ? (
            <ThumbnailProvenance status={status as AcquisitionScanStatus} />
          ) : null}
        </Stack>
      )}
    </Paper>
  );
}
