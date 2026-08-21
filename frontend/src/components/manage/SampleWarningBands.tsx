import { useState } from 'react';
import {
  Box,
  Collapse,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography
} from '@mui/material';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight';
import KeyboardDoubleArrowDownIcon from '@mui/icons-material/KeyboardDoubleArrowDown';
import KeyboardDoubleArrowUpIcon from '@mui/icons-material/KeyboardDoubleArrowUp';
import {
  AcqLabel,
  EntityDash,
  MdRunLabel,
  MessageList,
  ReconLabel,
  SampleCell,
  StillPresentCell,
  formatTs
} from './issueCells';
import {
  flattenBand,
  type SampleBand,
  type WarningInnerRow
} from './groupSampleWarnings';

export type BandVariant = 'outstanding' | 'resolved';

// The Acquisition column for one inner row: the acquisition name/actions on the
// first row of its group, an md_run pseudo-entity, a dash for a sample.toml
// row, or blank on continuation rows of an acquisition group (the shading,
// alternating acquisition to acquisition — not a repeated name or a dash —
// ties them together).
function AcqCell({
  r,
  sampleId
}: {
  readonly r: WarningInnerRow;
  readonly sampleId: string | null;
}) {
  if (r.mdRunId) {
    return <MdRunLabel mdRunId={r.mdRunId} sampleId={sampleId} />;
  }
  if (r.acq) {
    return r.showAcqLabel ? (
      <AcqLabel acq={r.acq} sampleId={sampleId} withActions={r.acqActions} />
    ) : null;
  }
  return <EntityDash />;
}

function InnerTable({
  band,
  variant
}: {
  readonly band: SampleBand;
  readonly variant: BandVariant;
}) {
  const rows = flattenBand(band);
  const trailingHeader =
    variant === 'resolved' ? 'Resolved at' : 'Still present as of';
  return (
    <Table size="small" sx={{ tableLayout: 'fixed' }}>
      <TableHead>
        <TableRow>
          <TableCell sx={{ width: '18%' }}>Acquisition(s)</TableCell>
          <TableCell sx={{ width: '18%' }}>Reconstruction(s)</TableCell>
          <TableCell sx={{ width: '44%' }}>Message(s)</TableCell>
          <TableCell sx={{ width: '20%' }}>{trailingHeader}</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map(r => (
          <TableRow
            key={r.id}
            sx={r.shaded ? { bgcolor: 'action.hover' } : undefined}
          >
            <TableCell sx={{ verticalAlign: 'top' }}>
              <AcqCell r={r} sampleId={band.sample_id} />
            </TableCell>
            <TableCell sx={{ verticalAlign: 'top' }}>
              {r.recon && r.acq ? (
                <ReconLabel
                  acq={r.acq}
                  recon={r.recon}
                  sampleId={band.sample_id}
                />
              ) : (
                <EntityDash />
              )}
            </TableCell>
            <TableCell sx={{ verticalAlign: 'top' }}>
              <MessageList messages={r.messages} />
            </TableCell>
            <TableCell sx={{ verticalAlign: 'top' }}>
              {variant === 'resolved' ? (
                <Typography sx={{ whiteSpace: 'nowrap' }} variant="body2">
                  {formatTs(r.resolved_at)}
                </Typography>
              ) : (
                <StillPresentCell
                  reEvaluated={r.reEvaluated}
                  timestamp={r.stillPresentAt}
                />
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// Shared expand/collapse-all state, lifted so callers can place the toggle
// button in their own toolbar (e.g. beside the filter input). Tracks only the
// closed bands so newly-arriving bands default to expanded.
export function useBandCollapse() {
  const [closed, setClosed] = useState<ReadonlySet<string>>(new Set());
  const toggleBand = (key: string) =>
    setClosed(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  return { closed, setClosed, toggleBand };
}

export type BandCollapse = ReturnType<typeof useBandCollapse>;

export function ExpandAllToggle({
  bandKeys,
  collapse
}: {
  readonly bandKeys: string[];
  readonly collapse: BandCollapse;
}) {
  const allOpen = bandKeys.every(k => !collapse.closed.has(k));
  return (
    <IconButton
      aria-label={allOpen ? 'Collapse all samples' : 'Expand all samples'}
      onClick={() =>
        collapse.setClosed(allOpen ? new Set(bandKeys) : new Set())
      }
      size="small"
    >
      {allOpen ? (
        <KeyboardDoubleArrowDownIcon />
      ) : (
        <KeyboardDoubleArrowUpIcon />
      )}
    </IconButton>
  );
}

function Band({
  band,
  variant,
  open,
  onToggle
}: {
  readonly band: SampleBand;
  readonly variant: BandVariant;
  readonly open: boolean;
  readonly onToggle: () => void;
}) {
  return (
    <Paper
      elevation={0}
      sx={{ border: 1, borderColor: 'divider', borderRadius: 2 }}
      variant="outlined"
    >
      <Stack
        alignItems="center"
        direction="row"
        spacing={0.5}
        sx={{
          p: 1,
          bgcolor: 'action.hover',
          borderBottom: open ? 1 : 0,
          borderColor: 'divider',
          borderTopLeftRadius: 8,
          borderTopRightRadius: 8
        }}
      >
        <IconButton
          aria-label={open ? 'Collapse sample' : 'Expand sample'}
          onClick={onToggle}
          size="small"
        >
          {open ? <KeyboardArrowDownIcon /> : <KeyboardArrowRightIcon />}
        </IconButton>
        <SampleCell
          fileKind={band.file_kind}
          sampleId={band.sample_id}
          samplePath={band.sample_path}
          showActions={band.hasSampleEdit}
        />
      </Stack>
      <Collapse in={open} unmountOnExit>
        <Box sx={{ p: 1 }}>
          <InnerTable band={band} variant={variant} />
        </Box>
      </Collapse>
    </Paper>
  );
}

// A list of sample bands (the sample-centric warnings layout). Shared by the
// outstanding and recently-resolved tables — `variant` only swaps the trailing
// column (still-present vs resolved-at).
export function SampleWarningBands({
  bands,
  variant,
  collapse
}: {
  readonly bands: SampleBand[];
  readonly variant: BandVariant;
  // Omit to let the component own its collapse state (no external toggle).
  readonly collapse?: BandCollapse;
}) {
  const internal = useBandCollapse();
  const c = collapse ?? internal;
  return (
    <Stack spacing={1.5}>
      {bands.map(band => (
        <Band
          band={band}
          key={band.key}
          onToggle={() => c.toggleBand(band.key)}
          open={!c.closed.has(band.key)}
          variant={variant}
        />
      ))}
    </Stack>
  );
}
