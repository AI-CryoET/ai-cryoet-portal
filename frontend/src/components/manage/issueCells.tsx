import { useMemo, type Dispatch, type SetStateAction } from 'react';
import { Box, Chip, Stack, Tooltip, Typography } from '@mui/material';
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
  type MRT_ColumnSizingState
} from 'material-react-table';
import EditNoteIcon from '@mui/icons-material/EditNote';
import { CustomLink, IconButtonLink } from '~/components/CustomLink';
import { CopyIconButton } from '~/components/common/CopyIconButton';
import type { IssueGroup } from '~/types';
import type {
  AffectedAcquisition,
  AffectedReconstruction
} from './groupSampleWarnings';

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
// "Edit file" action folds in here (copy-path + edit-metadata icons) — the
// message itself lives in the Message(s) column (see MessagesListCell).
export function SampleCell({
  sampleId,
  samplePath = null,
  fileKind,
  mdRunId = null,
  showActions = false
}: {
  readonly sampleId: string | null;
  readonly samplePath?: string | null;
  readonly fileKind?: string;
  readonly mdRunId?: string | null;
  readonly showActions?: boolean;
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
    </Stack>
  );
}

function EntityDash() {
  return (
    <Typography color="text.secondary" variant="body2">
      —
    </Typography>
  );
}

// Acquisition name + actions. When the issue is reconstruction-owned the
// acquisition is only grouping context — its copy-path/edit icons would point
// at acquisition.toml, but the fix lives in the reconstruction, so drop them.
function AcqLabel({
  acq,
  reconOwned,
  row
}: {
  readonly acq: AffectedAcquisition;
  readonly reconOwned: boolean;
  readonly row: {
    sample_id: string | null;
    file_kind: string;
    md_run_id: string | null;
  };
}) {
  const editLink = reconOwned
    ? null
    : authorLinkFor({
        file_kind: row.file_kind,
        sample_id: row.sample_id,
        acquisition_id: acq.acquisition_id,
        md_run_id: row.md_run_id
      });
  return (
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
      {acq.acquisition_path && !reconOwned ? (
        <CopyIconButton text={acq.acquisition_path} tooltip="Copy path" />
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
    </Stack>
  );
}

// Reconstruction name (plain text, no detail page) + copy-path (derived,
// skipped when acquisition_path is null) + edit-metadata (author form's
// "reconstruction" tab).
function ReconLabel({
  acq,
  recon,
  sampleId
}: {
  readonly acq: AffectedAcquisition;
  readonly recon: AffectedReconstruction;
  readonly sampleId: string | null;
}) {
  const path = reconstructionPath(
    acq.acquisition_path,
    recon.reconstruction_alignment_id
  );
  return (
    <Stack
      alignItems="center"
      direction="row"
      spacing={0.25}
      sx={{ minWidth: 0 }}
    >
      <Typography sx={ellipsisSx} variant="body2">
        {recon.reconstruction_alignment_id}
      </Typography>
      {path ? <CopyIconButton text={path} tooltip="Copy path" /> : null}
      <Tooltip title="Edit metadata">
        <IconButtonLink
          aria-label="Edit metadata"
          search={{
            tab: 'reconstruction',
            id: recon.reconstruction_alignment_id,
            sampleId: sampleId ?? '',
            acquisitionId: recon.acquisition_id
          }}
          size="small"
          to="/manage/author"
        >
          <EditNoteIcon fontSize="small" />
        </IconButtonLink>
      </Tooltip>
    </Stack>
  );
}

// One or more warning messages as bullet lines — wrapping, no truncation (the
// table row grows taller instead), so several warnings on one entity read as
// distinct items. A dash when the entity has no message of its own.
function MessageLines({ messages }: { readonly messages: string[] }) {
  if (messages.length === 0) {
    return <EntityDash />;
  }
  // Column stack so multiple messages on one entity sit one above the other
  // (the cell's own layout would otherwise lay these siblings out in a row).
  return (
    <Stack spacing={0.5} sx={{ minWidth: 0 }}>
      {messages.map((m, i) => (
        <Stack
          direction="row"
          key={`${i}-${m}`}
          spacing={0.75}
          sx={{ minWidth: 0 }}
        >
          <Typography color="text.secondary" variant="body2">
            •
          </Typography>
          <Typography
            sx={{
              minWidth: 0,
              whiteSpace: 'normal',
              // Messages embed long, space-less file/folder paths; break them
              // mid-token so they wrap instead of overflowing the column.
              overflowWrap: 'anywhere'
            }}
            variant="body2"
          >
            {m}
          </Typography>
        </Stack>
      ))}
    </Stack>
  );
}

// The scalar fields of a SampleWarningRow that the affected sub-table needs
// (edit links are keyed off sample/acquisition/run identity).
export interface AffectedRow {
  sample_id: string | null;
  md_run_id: string | null;
  file_kind: string;
  message: string;
  acquisitions: AffectedAcquisition[];
}

// One flattened line of the affected sub-table: a real row per reconstruction
// (or per acquisition-owned warning, or one line for a sample/run-scoped row).
// `firstOfAcq` renders the acquisition label only on its first line so it reads
// as a group header without a rowSpan.
interface AffectedInnerRow {
  id: string;
  acq: AffectedAcquisition | null;
  recon: AffectedReconstruction | null;
  messages: string[];
  firstOfAcq: boolean;
}

function flattenAffected(row: AffectedRow): AffectedInnerRow[] {
  if (row.acquisitions.length === 0) {
    return [
      {
        id: 'scalar',
        acq: null,
        recon: null,
        messages: row.message ? [row.message] : [],
        firstOfAcq: true
      }
    ];
  }
  const out: AffectedInnerRow[] = [];
  for (const acq of row.acquisitions) {
    if (acq.reconstructions.length === 0) {
      out.push({
        id: acq.acquisition_id,
        acq,
        recon: null,
        messages: acq.messages,
        firstOfAcq: true
      });
    } else {
      acq.reconstructions.forEach((recon, j) => {
        out.push({
          id: `${acq.acquisition_id}/${recon.reconstruction_alignment_id}`,
          acq,
          recon,
          messages: recon.messages,
          firstOfAcq: j === 0
        });
      });
    }
  }
  return out;
}

// The Acquisition / Reconstruction / Message(s) detail sub-table, rendered in
// each outer row's expandable detail panel. Real rows (one per reconstruction)
// make a reconstruction line up with its message for free — the rowSpan the
// merged CSS-grid column used to fake. Column widths are lifted to the parent
// (`columnSizing` / `onColumnSizingChange`) so resizing one panel resizes every
// panel in the table, keeping the sub-columns consistent.
export function AffectedTable({
  row,
  columnSizing,
  onColumnSizingChange
}: {
  readonly row: AffectedRow;
  readonly columnSizing: MRT_ColumnSizingState;
  readonly onColumnSizingChange: Dispatch<
    SetStateAction<MRT_ColumnSizingState>
  >;
}) {
  const data = useMemo(() => flattenAffected(row), [row]);
  const columns = useMemo<MRT_ColumnDef<AffectedInnerRow>[]>(
    () => [
      {
        id: 'acquisition',
        header: 'Acquisition(s)',
        size: 150,
        Cell: ({ row: r }) =>
          r.original.acq && r.original.firstOfAcq ? (
            <AcqLabel
              acq={r.original.acq}
              reconOwned={r.original.recon != null}
              row={row}
            />
          ) : (
            <EntityDash />
          )
      },
      {
        id: 'reconstruction',
        header: 'Reconstruction(s)',
        size: 150,
        Cell: ({ row: r }) =>
          r.original.acq && r.original.recon ? (
            <ReconLabel
              acq={r.original.acq}
              recon={r.original.recon}
              sampleId={row.sample_id}
            />
          ) : (
            <EntityDash />
          )
      },
      {
        id: 'messages',
        header: 'Message(s)',
        size: 560,
        muiTableBodyCellProps: { sx: { whiteSpace: 'normal' } },
        Cell: ({ row: r }) => <MessageLines messages={r.original.messages} />
      }
    ],
    [row]
  );

  const table = useMaterialReactTable<AffectedInnerRow>({
    columns,
    data,
    getRowId: r => r.id,
    layoutMode: 'grid',
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
    defaultColumn: { grow: 1 },
    enableSorting: false,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableGlobalFilter: false,
    enablePagination: false,
    enableTopToolbar: false,
    enableBottomToolbar: false,
    muiTableBodyRowProps: { hover: false },
    state: { columnSizing },
    onColumnSizingChange,
    mrtTheme: theme => ({ draggingBorderColor: theme.palette.grey[300] }),
    initialState: { density: 'compact' },
    // A bordered white table on the grey panel below — same visual treatment as
    // the nested acquisition tables on the /data pages.
    muiTablePaperProps: {
      elevation: 0,
      sx: {
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        bgcolor: 'background.paper'
      }
    }
  });

  // Grey inset frame (like /data's AcquisitionsSubTable) so the nested table
  // reads as a sub-table; `defaultColumn.grow` + layoutMode:grid let its columns
  // fill most of the outer table's width by default.
  return (
    <Box sx={{ p: 2, bgcolor: 'action.hover', width: '100%' }}>
      <MaterialReactTable table={table} />
    </Box>
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
