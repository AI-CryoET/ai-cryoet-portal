import {
  Box,
  Chip,
  IconButton,
  Stack,
  Tooltip,
  Typography
} from '@mui/material';
import EditNoteIcon from '@mui/icons-material/EditNote';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { CustomLink, IconButtonLink } from '~/components/CustomLink';
import { CopyIconButton } from '~/components/common/CopyIconButton';
import type { IssueGroup } from '~/types';
import { computeBands, type AffectedAcquisition } from './groupSampleWarnings';

// Path convention baked into the (shortened) assembler.py message strings:
// a reconstruction-alignment group always lives directly under its
// acquisition's `Reconstructions/<group>` folder. No stored `path` column
// exists on ReconstructionAlignmentORM, so this is derived client-side.
function reconstructionPath(
  acquisitionPath: string | null,
  reconstructionId: string
): string | null {
  return acquisitionPath
    ? `${acquisitionPath}/Reconstructions/${reconstructionId}`
    : null;
}

// Issue timestamps are Unix seconds; render in the viewer's locale.
export function formatTs(seconds: number | null | undefined): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleString(undefined, {
    timeZoneName: 'short'
  });
}

// First-seen wants a date-only reading (matches the wireframe's "2026-06-18").
export function formatDate(seconds: number | null | undefined): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleDateString();
}

// Single-line ellipsis truncation for cells that shouldn't wrap (name/id
// columns) — pairs with a Tooltip showing the full value. Also used inside a
// flex row (Stack), so callers should give the wrapping Box `minWidth: 0` (a
// flex child otherwise refuses to shrink below its content width, which
// silently defeats the ellipsis).
const ellipsisSx = {
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  minWidth: 0
} as const;

// Wrap normally, then clamp to a fixed number of lines with an ellipsis —
// for free text (warning type / message) that should read in full when short
// but not blow out the row height when long.
const lineClampSx = (lines: number) =>
  ({
    display: '-webkit-box',
    WebkitLineClamp: lines,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
    minWidth: 0
  }) as const;

const SEVERITY_COLOR = {
  error: 'error',
  warning: 'warning',
  info: 'info'
} as const;

export function SeverityPill({
  severity
}: {
  readonly severity: IssueGroup['severity'];
}) {
  return (
    <Chip
      color={SEVERITY_COLOR[severity]}
      label={severity}
      size="small"
      variant="outlined"
    />
  );
}

// Edit link for an authorable file: a sample.toml / acquisition.toml /
// md_run.toml warning row jumps straight into the matching authoring form,
// auto-loaded by id (issue 07). Acquisition identity is composite, so the
// link carries both ids (mirrors the acquisition detail-page "Edit
// acquisition.toml" link). An md_run_toml row without a resolvable md_run_id
// (e.g. a deprecated legacy [[md_run]] block, which names no single run) has
// no link either. Other file kinds (mdoc, mrc, run-scope, …) have no form —
// returns null.
export function authorLinkFor(
  group: Pick<
    IssueGroup,
    'file_kind' | 'sample_id' | 'acquisition_id' | 'md_run_id'
  >
): { to: string; search: Record<string, string> } | null {
  if (group.file_kind === 'sample_toml' && group.sample_id) {
    return {
      to: '/manage/author',
      search: { tab: 'sample', id: group.sample_id }
    };
  }
  if (
    group.file_kind === 'acquisition_toml' &&
    group.sample_id &&
    group.acquisition_id
  ) {
    return {
      to: '/manage/author',
      search: {
        tab: 'acquisition',
        id: group.acquisition_id,
        sampleId: group.sample_id
      }
    };
  }
  if (group.file_kind === 'md_run_toml' && group.md_run_id) {
    return {
      to: '/manage/author',
      search: { tab: 'md_run', id: group.md_run_id }
    };
  }
  return null;
}

// Warning type — plain wrapped text (no chip/pill), clamped to a couple of
// lines so a long category name can't blow out the row height.
export function WarningTypeCell({ category }: { readonly category: string }) {
  return (
    <Typography sx={lineClampSx(2)} variant="body2">
      {category.replaceAll('_', ' ')}
    </Typography>
  );
}

// Sample link for a regrouped SampleWarningRow. Truncates to one line
// (ellipsis) rather than wrapping. When the row is sample/md_run-scoped
// (`showActions`, i.e. `row.acquisitions.length === 0`) the row-level
// "Edit file" action folds in here (copy-path + edit-metadata icons), plus
// an info icon with the row's message on hover — there's no acquisitions
// column to hang it on for these rows.
export function SampleCell({
  sampleId,
  samplePath = null,
  fileKind,
  mdRunId = null,
  showActions = false,
  message
}: {
  readonly sampleId: string | null;
  readonly samplePath?: string | null;
  readonly fileKind?: string;
  readonly mdRunId?: string | null;
  readonly showActions?: boolean;
  readonly message?: string;
}) {
  if (sampleId == null) {
    return (
      <Typography color="text.secondary" variant="body2">
        Scan (run-level)
      </Typography>
    );
  }
  const editLink =
    showActions && fileKind
      ? authorLinkFor({
          file_kind: fileKind,
          sample_id: sampleId,
          acquisition_id: null,
          md_run_id: mdRunId
        })
      : null;
  return (
    <Stack
      alignItems="center"
      direction="row"
      spacing={0.25}
      sx={{ minWidth: 0 }}
    >
      <Box sx={ellipsisSx}>
        <CustomLink params={{ sampleId }} to="/samples/$sampleId">
          {sampleId}
        </CustomLink>
      </Box>
      {showActions && samplePath ? (
        <CopyIconButton text={samplePath} tooltip="Copy path" />
      ) : null}
      {editLink ? (
        <Tooltip title="Edit metadata">
          <IconButtonLink
            aria-label="Edit metadata"
            search={editLink.search}
            size="small"
            to={editLink.to}
          >
            <EditNoteIcon fontSize="small" />
          </IconButtonLink>
        </Tooltip>
      ) : null}
      {showActions && message ? (
        <Tooltip title={message}>
          <IconButton aria-label="View message" size="small">
            <InfoOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      ) : null}
    </Stack>
  );
}

// Row height of one acquisition "band" — shared with the (later) Reconstructions
// column so both cells' bands line up: same order, same height, same
// alternating color, all derived from the same `row.acquisitions` array.
const BAND_LINE_HEIGHT_PX = 32;

// Every acquisition affected by a sample+category warning row: name (linking
// to the acquisition detail page), a copy-path button, an edit-metadata icon
// where an authoring form exists for this row's file_kind, and an info icon
// with this acquisition's own message on hover. A dash means the warning is
// sample- or run-level, with no acquisition to list. Rendered in
// alternating-shaded "bands" (one per acquisition), each `flex`-grown by its
// `lineCount` share so the bands fill the table row's full height edge to
// edge (rather than a fixed minHeight that leaves blank space below the last
// band when another column forces a taller row). The outer Stack needs
// `alignSelf: 'stretch'` too — MRT's grid layout mode puts `alignItems:
// 'center'` on the `<td>` itself, which otherwise vertically centers (and
// shrinks) the whole Stack instead of letting it fill the cell height. It
// also needs `flexGrow: 1` for the *width* — the `<td>`'s own flex-direction
// is row, so without a grow factor the Stack shrinks to its content's width
// instead of filling a wide (or user-resized) column, leaving the bands'
// background short of the column's actual right edge. The table
// also zeroes this column's own cell padding (`muiTableBodyCellProps`) so
// each band's background can bleed all the way to the column's true edges —
// each Box supplies its own `px` inset instead — otherwise the cell's
// default padding left an unshaded margin down both sides that broke the
// contiguous-row illusion. This column stays visually aligned with the
// Reconstructions column, which derives identical bands from the same input
// and grows by the same shares.
export function AcquisitionListCell({
  row
}: {
  readonly row: {
    sample_id: string | null;
    md_run_id: string | null;
    file_kind: string;
    acquisitions: AffectedAcquisition[];
  };
}) {
  if (row.acquisitions.length === 0) {
    return (
      <Typography color="text.secondary" px={1.5} variant="body2">
        —
      </Typography>
    );
  }
  const bands = computeBands(row.acquisitions);
  return (
    <Stack
      spacing={0}
      sx={{ alignSelf: 'stretch', flexGrow: 1, height: '100%', minWidth: 0 }}
    >
      {row.acquisitions.map((acq, i) => {
        const ownMessage = acq.messages.join('; ');
        const editLink = authorLinkFor({
          file_kind: row.file_kind,
          sample_id: row.sample_id,
          acquisition_id: acq.acquisition_id,
          md_run_id: row.md_run_id
        });
        const band = bands[i];
        return (
          <Box
            key={acq.acquisition_id}
            sx={{
              display: 'flex',
              alignItems: 'center',
              flex: `${band.lineCount} 0 ${band.lineCount * BAND_LINE_HEIGHT_PX}px`,
              bgcolor: i % 2 === 1 ? 'grey.100' : 'transparent',
              px: 1.5,
              minWidth: 0
            }}
          >
            <Stack
              alignItems="center"
              direction="row"
              spacing={0.25}
              sx={{ minWidth: 0 }}
            >
              <Box sx={ellipsisSx}>
                <CustomLink
                  params={{ acquisitionId: acq.acquisition_id }}
                  search={{ sampleId: row.sample_id ?? '' }}
                  to="/acquisitions/$acquisitionId"
                >
                  {acq.acquisition_id}
                </CustomLink>
              </Box>
              {acq.acquisition_path ? (
                <CopyIconButton
                  text={acq.acquisition_path}
                  tooltip="Copy path"
                />
              ) : null}
              {editLink ? (
                <Tooltip title="Edit metadata">
                  <IconButtonLink
                    aria-label="Edit metadata"
                    search={editLink.search}
                    size="small"
                    to={editLink.to}
                  >
                    <EditNoteIcon fontSize="small" />
                  </IconButtonLink>
                </Tooltip>
              ) : null}
              <Tooltip title={ownMessage}>
                <IconButton aria-label="View message" size="small">
                  <InfoOutlinedIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
          </Box>
        );
      })}
    </Stack>
  );
}

// Reconstruction-alignment groups affected by this row, one column over from
// Acquisitions. Bands come from the exact same `computeBands` call over the
// same `row.acquisitions` array as `AcquisitionListCell`, so the two columns'
// stripes/heights (and now flex-grow shares) line up row-for-row without any
// cross-column coordination. Reconstruction name is plain text (no detail
// page to link to); each still gets a copy-path icon (derived path, skipped
// when acquisition_path is null), an edit-metadata icon (the author form's
// "reconstruction" tab), and an info icon with its own message on hover.
export function ReconstructionsListCell({
  row
}: {
  readonly row: {
    sample_id: string | null;
    acquisitions: AffectedAcquisition[];
  };
}) {
  if (row.acquisitions.length === 0) {
    return (
      <Typography color="text.secondary" px={1.5} variant="body2">
        —
      </Typography>
    );
  }
  const bands = computeBands(row.acquisitions);
  return (
    <Stack
      spacing={0}
      sx={{ alignSelf: 'stretch', flexGrow: 1, height: '100%', minWidth: 0 }}
    >
      {row.acquisitions.map((acq, i) => {
        const band = bands[i];
        return (
          <Box
            key={acq.acquisition_id}
            sx={{
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              flex: `${band.lineCount} 0 ${band.lineCount * BAND_LINE_HEIGHT_PX}px`,
              bgcolor: i % 2 === 1 ? 'grey.100' : 'transparent',
              px: 1.5,
              minWidth: 0
            }}
          >
            {acq.reconstructions.length === 0 ? (
              <Typography color="text.secondary" variant="body2">
                —
              </Typography>
            ) : (
              acq.reconstructions.map(recon => {
                const ownMessage = recon.messages.join('; ');
                const path = reconstructionPath(
                  acq.acquisition_path,
                  recon.reconstruction_alignment_id
                );
                return (
                  <Stack
                    alignItems="center"
                    direction="row"
                    key={recon.reconstruction_alignment_id}
                    spacing={0.25}
                    sx={{ minWidth: 0 }}
                  >
                    <Typography sx={ellipsisSx} variant="body2">
                      {recon.reconstruction_alignment_id}
                    </Typography>
                    {path ? (
                      <CopyIconButton text={path} tooltip="Copy path" />
                    ) : null}
                    <Tooltip title="Edit metadata">
                      <IconButtonLink
                        aria-label="Edit metadata"
                        search={{
                          tab: 'reconstruction',
                          id: recon.reconstruction_alignment_id,
                          sampleId: row.sample_id ?? '',
                          acquisitionId: recon.acquisition_id
                        }}
                        size="small"
                        to="/manage/author"
                      >
                        <EditNoteIcon fontSize="small" />
                      </IconButtonLink>
                    </Tooltip>
                    <Tooltip title={ownMessage}>
                      <IconButton aria-label="View message" size="small">
                        <InfoOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Stack>
                );
              })
            )}
          </Box>
        );
      })}
    </Stack>
  );
}

// "Still present as of" (plan §9.7): when the owner was re-evaluated this run
// (`last_seen_run_id === latest_run_id`) show the global latest-scan timestamp;
// otherwise the owner was skipped — show its stale `last_seen_at` with a
// tooltip explaining it wasn't re-checked.
export function StillPresentCell({
  reEvaluated,
  timestamp
}: {
  readonly reEvaluated: boolean;
  readonly timestamp: number | null | undefined;
}) {
  if (reEvaluated) {
    return (
      <Typography sx={{ whiteSpace: 'nowrap' }} variant="body2">
        {formatTs(timestamp)}
      </Typography>
    );
  }
  return (
    <Tooltip title="owner skipped — not re-checked">
      <Typography
        sx={{ whiteSpace: 'nowrap', color: 'warning.main' }}
        variant="body2"
      >
        {formatTs(timestamp)}
      </Typography>
    </Tooltip>
  );
}
