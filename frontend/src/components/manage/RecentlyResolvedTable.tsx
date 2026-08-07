import { useMemo } from 'react';
import { alpha } from '@mui/material';
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef
} from 'material-react-table';
import type { IssueGroup } from '~/types';
import { useRecentlyResolvedQuery } from '~/utils/queryOptions';
import {
  EntityCell,
  FileCell,
  IssuesCell,
  SeverityPill,
  formatDate,
  formatTs,
  issueRowId
} from './issueCells';

function useColumns(): MRT_ColumnDef<IssueGroup>[] {
  return useMemo(
    () => [
      {
        id: 'entity',
        header: 'Sample / Acquisition',
        size: 220,
        Cell: ({ row }) => <EntityCell group={row.original} />
      },
      {
        id: 'file',
        header: 'File',
        size: 260,
        Cell: ({ row }) => <FileCell group={row.original} />
      },
      {
        accessorKey: 'severity',
        header: 'Severity',
        size: 110,
        Cell: ({ row }) => <SeverityPill severity={row.original.severity} />
      },
      {
        id: 'issues',
        header: 'Issues',
        Cell: ({ row }) => <IssuesCell group={row.original} />
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
  const { data } = useRecentlyResolvedQuery(withinHours);
  const columns = useColumns();

  const table = useMaterialReactTable<IssueGroup>({
    columns,
    data,
    getRowId: issueRowId,
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
