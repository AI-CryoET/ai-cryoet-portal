import { useMemo } from 'react';
import { Chip, Stack, Typography } from '@mui/material';
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef
} from 'material-react-table';
import { CustomLink } from '~/components/CustomLink';
import type { ScanRun } from '~/types';

// Scan timestamps are Unix seconds; render in the viewer's locale.
function formatTs(seconds: number | null): string {
  if (seconds == null) {
    return '—';
  }
  return new Date(seconds * 1000).toLocaleString(undefined, {
    timeZoneName: 'short'
  });
}

// Whole-second duration → "Xm Ys"; null while the scan is still running.
function formatDuration(run: ScanRun): string {
  if (run.ended_at == null) {
    return '—';
  }
  const secs = Math.max(0, Math.round(run.ended_at - run.started_at));
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

const count = (v: number | null) => (v == null ? '—' : v.toLocaleString());

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

export function ScanHistoryTable({ rows }: { readonly rows: ScanRun[] }) {
  const columns = useMemo<MRT_ColumnDef<ScanRun>[]>(
    () => [
      {
        accessorKey: 'scan_run_id',
        header: 'Scan ID',
        size: 200,
        Cell: ({ row }) => (
          <CustomLink
            params={{ scanId: row.original.scan_run_id }}
            sx={{ fontFamily: 'monospace', fontSize: 12.5 }}
            to="/manage/scans/$scanId"
          >
            {row.original.scan_run_id}
          </CustomLink>
        )
      },
      {
        accessorKey: 'started_at',
        header: 'Started',
        Cell: ({ cell }) => formatTs(cell.getValue<number>())
      },
      {
        id: 'duration',
        header: 'Duration',
        size: 110,
        Cell: ({ row }) => formatDuration(row.original)
      },
      {
        accessorKey: 'status',
        header: 'Status',
        size: 120,
        Cell: ({ cell }) => {
          const status = cell.getValue<string>();
          return (
            <Chip
              color={statusColor(status)}
              label={status}
              size="small"
              variant="outlined"
            />
          );
        }
      },
      {
        accessorKey: 'n_upserted',
        header: 'Updated',
        size: 100,
        Cell: ({ cell }) => count(cell.getValue<number | null>())
      },
      {
        accessorKey: 'n_skipped',
        header: 'Skipped',
        size: 100,
        Cell: ({ cell }) => count(cell.getValue<number | null>())
      },
      {
        accessorKey: 'n_failed',
        header: 'Failed',
        size: 100,
        Cell: ({ cell }) => count(cell.getValue<number | null>())
      },
      {
        id: 'warns_errs',
        header: 'Warns / Errs',
        size: 140,
        Cell: ({ row }) => {
          const { n_warning_active, n_error_active } = row.original;
          return (
            <Stack direction="row" spacing={0.5}>
              <Chip
                color="warning"
                label={`${n_warning_active ?? 0} warn`}
                size="small"
                variant="outlined"
              />
              <Chip
                color="error"
                label={`${n_error_active ?? 0} err`}
                size="small"
                variant="outlined"
              />
            </Stack>
          );
        }
      }
    ],
    []
  );

  const table = useMaterialReactTable<ScanRun>({
    columns,
    data: rows,
    getRowId: r => r.scan_run_id,
    enableColumnActions: false,
    enableColumnFilters: false,
    enableGlobalFilter: false,
    // Drop the whole internal-actions cluster (density/hide/fullscreen) so the
    // top toolbar holds only the pagination — no empty button slot.
    enableToolbarInternalActions: false,
    enableSorting: true,
    // Paginated, 10 rows by default; pagination sits in the top toolbar.
    enablePagination: true,
    positionPagination: 'top',
    enableBottomToolbar: false,
    // Most recent scan first.
    initialState: {
      density: 'comfortable',
      sorting: [{ id: 'started_at', desc: true }],
      pagination: { pageSize: 10, pageIndex: 0 }
    },
    // Match the portal tables (/data, /experimental, /md-simulation).
    muiTablePaperProps: {
      elevation: 0,
      sx: { border: 1, borderColor: 'divider', borderRadius: 2 }
    },
    localization: { noRecordsToDisplay: 'No scans recorded yet.' },
    renderEmptyRowsFallback: () => (
      <Typography color="text.secondary" sx={{ p: 2 }} variant="body2">
        No scans recorded yet.
      </Typography>
    )
  });

  return <MaterialReactTable table={table} />;
}
