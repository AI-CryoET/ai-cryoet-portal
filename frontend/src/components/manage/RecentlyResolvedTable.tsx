import { useMemo } from 'react';
import { alpha } from '@mui/material';
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef
} from 'material-react-table';
import { useRecentlyResolvedQuery } from '~/utils/queryOptions';
import {
  AcquisitionListCell,
  CategoryChip,
  MessageCell,
  RowFileCell,
  SampleCell,
  SeverityPill,
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
        id: 'sample',
        header: 'Sample',
        size: 160,
        Cell: ({ row }) => <SampleCell sampleId={row.original.sample_id} />
      },
      {
        id: 'file',
        header: 'File',
        size: 160,
        Cell: ({ row }) => (
          <RowFileCell
            fileKind={row.original.file_kind}
            mdRunId={row.original.md_run_id}
            sampleId={row.original.sample_id}
          />
        )
      },
      {
        id: 'category',
        header: 'Warning type',
        size: 170,
        Cell: ({ row }) => <CategoryChip category={row.original.category} />
      },
      {
        accessorKey: 'severity',
        header: 'Severity',
        size: 110,
        Cell: ({ row }) => <SeverityPill severity={row.original.severity} />
      },
      {
        id: 'message',
        header: 'Message',
        size: 260,
        Cell: ({ row }) => <MessageCell message={row.original.message} />
      },
      {
        id: 'acquisitions',
        header: 'Affected acquisitions',
        size: 220,
        Cell: ({ row }) => <AcquisitionListCell row={row.original} />
      },
      {
        accessorKey: 'first_seen_at',
        header: 'First seen',
        size: 130,
        Cell: ({ cell }) => formatDate(cell.getValue<number>())
      },
      {
        accessorKey: 'resolved_at',
        header: 'Resolved at',
        size: 170,
        Cell: ({ cell }) => formatTs(cell.getValue<number | null | undefined>())
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

  const table = useMaterialReactTable<SampleWarningRow>({
    columns,
    data,
    getRowId: row => row.key,
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
      pagination: { pageSize: 10, pageIndex: 0 }
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
