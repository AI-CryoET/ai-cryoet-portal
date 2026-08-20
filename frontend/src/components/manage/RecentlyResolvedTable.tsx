import { useMemo, useState } from 'react';
import { Typography, alpha } from '@mui/material';
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef,
  type MRT_ColumnSizingState
} from 'material-react-table';
import { useRecentlyResolvedQuery } from '~/utils/queryOptions';
import {
  AffectedTable,
  SampleCell,
  SeverityPill,
  WarningTypeCell,
  formatDate,
  formatTs
} from './issueCells';
import {
  groupSampleWarnings,
  type SampleWarningRow
} from './groupSampleWarnings';

function useColumns(): MRT_ColumnDef<SampleWarningRow>[] {
  return useMemo(
    () => [
      {
        accessorKey: 'category',
        header: 'Warning type',
        size: 125,
        Cell: ({ row }) => <WarningTypeCell category={row.original.category} />
      },
      {
        accessorKey: 'severity',
        header: 'Severity',
        size: 95,
        Cell: ({ row }) => <SeverityPill severity={row.original.severity} />
      },
      {
        id: 'sample',
        header: 'Sample',
        size: 135,
        Cell: ({ row }) => (
          <SampleCell
            fileKind={row.original.file_kind}
            mdRunId={row.original.md_run_id}
            sampleId={row.original.sample_id}
            samplePath={row.original.sample_path}
            showActions={row.original.acquisitions.length === 0}
          />
        )
      },
      {
        accessorKey: 'first_seen_at',
        header: 'First seen',
        size: 85,
        Cell: ({ cell }) => formatDate(cell.getValue<number>())
      },
      {
        accessorKey: 'resolved_at',
        header: 'Resolved at',
        // Wide enough for the full "M/D/YYYY, H:MM:SS AM/PM TZ" string
        // (`formatTs`) without clipping — see the matching comment on
        // OutstandingIssuesTable's "Still present as of" column.
        size: 190,
        // Wrapped with `whiteSpace: nowrap` — bare text here word-wraps at
        // the comma/spaces in `formatTs`'s output (unlike `StillPresentCell`,
        // which already sets this), verified in a real browser: at this
        // column width it silently wrapped to two lines instead of clipping.
        Cell: ({ cell }) => (
          <Typography sx={{ whiteSpace: 'nowrap' }} variant="body2">
            {formatTs(cell.getValue<number | null | undefined>())}
          </Typography>
        )
      }
    ],
    []
  );
}

export function RecentlyResolvedTable({
  withinHours = 24
}: {
  readonly withinHours?: number;
}) {
  const { data: rawData } = useRecentlyResolvedQuery(withinHours);
  const data = useMemo(() => groupSampleWarnings(rawData), [rawData]);
  const columns = useColumns();
  // Shared affected sub-table column widths across every detail panel.
  const [affectedSizing, setAffectedSizing] = useState<MRT_ColumnSizingState>(
    {}
  );

  const table = useMaterialReactTable<SampleWarningRow>({
    columns,
    data,
    getRowId: row => row.key,
    // Fixed column widths that the user can drag-resize, sized to fit without
    // horizontal scroll (see column `size`s above). The 1440px viewport's
    // actual table content area is ~1150px wide (the page's centered
    // MuiContainer + card padding eat the rest) — verified in a real browser,
    // not just by summing the `size`s against the raw viewport width.
    layoutMode: 'grid',
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
    mrtTheme: theme => ({ draggingBorderColor: theme.palette.grey[300] }),
    defaultColumn: { grow: 1 },
    // Acquisitions / reconstructions / messages in an expandable detail panel,
    // open by default (see OutstandingIssuesTable / AffectedTable).
    renderDetailPanel: ({ row }) => (
      <AffectedTable
        columnSizing={affectedSizing}
        onColumnSizingChange={setAffectedSizing}
        row={row.original}
      />
    ),
    displayColumnDefOptions: {
      'mrt-row-expand': { size: 60, grow: false }
    },
    // Stretch the panel to the full cell width (see OutstandingIssuesTable).
    muiDetailPanelProps: { sx: { p: 0, flexDirection: 'column' } },
    muiTableBodyRowProps: { hover: false },
    enableColumnActions: false,
    enableColumnFilters: false,
    enableGlobalFilter: false,
    // Drop the whole internal-actions cluster (density/hide/fullscreen) so the
    // top toolbar holds only the pagination — no empty button slot.
    enableToolbarInternalActions: false,
    enableSorting: true,
    // Paginated, 10 rows by default; the pagination bar (rows-per-page + page
    // nav) shows at both top and bottom, matching the portal tables (/data).
    enablePagination: true,
    positionPagination: 'both',
    muiTopToolbarProps: {
      sx: { bgcolor: t => alpha(t.palette.primary.main, 0.12) }
    },
    initialState: {
      density: 'comfortable',
      sorting: [{ id: 'resolved_at', desc: true }],
      pagination: { pageSize: 10, pageIndex: 0 },
      expanded: true
    },
    // Match the portal tables (/data, /experimental, /md-simulation).
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 }
    },
    localization: {
      noRecordsToDisplay: 'Nothing resolved in the last 24 hours.'
    }
  });

  return <MaterialReactTable table={table} />;
}
