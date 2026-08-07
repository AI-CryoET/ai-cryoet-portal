import { memo, useMemo } from 'react';
import { alpha, Box, Tooltip } from '@mui/material';
import {
  MaterialReactTable,
  useMaterialReactTable,
  type MRT_ColumnDef
} from 'material-react-table';
import type { SampleSummary } from '~/types';
import type { SamplesSearchParams } from '~/utils/samplesSearch';
import { CustomLink } from '~/components/CustomLink';
import {
  PreviewThumbnail,
  thumbnailUrl,
  mdPreviewBySampleUrl
} from '~/components/common/Thumbnail';
import { AcquisitionsSubTable } from './AcquisitionsSubTable';

const dash = (v: unknown) => (v == null || v === '' ? '—' : String(v));

// Shared truncation styles for cells whose content is wrapped (so the ellipsis
// belongs to the same element the tooltip is attached to).
const ellipsisSx = {
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap'
} as const;

// memo: props (rows/filters/expandAllDetails) are all derived from the parent's
// debounced search, so they only change every 300ms. Without memo the whole
// table — and every mounted acquisition sub-table — re-renders on every
// keystroke as the URL search updates immediately. This is the filtering-lag fix.
export const SamplesPortalTable = memo(
  (props: {
    readonly rows: SampleSummary[];
    readonly loading?: boolean;
    // Active search params threaded to each acquisition subtable for client-side
    // filtering (mirrors the server EXISTS).
    readonly filters?: SamplesSearchParams;
    // Set true (by the browser, from committed/debounced state) when any
    // acquisition-entity filter is active, so every detail panel opens to show
    // the filtered acquisitions.
    readonly expandAllDetails?: boolean;
  }) => {
    const { rows, loading, filters, expandAllDetails } = props;

    const columns = useMemo<MRT_ColumnDef<SampleSummary>[]>(
      () => [
        {
          id: 'thumbnail',
          header: '',
          columnDefType: 'display',
          size: 80,
          grow: 0, // fixed-size image; growing it just pads the cell

          Cell: ({ row }) => {
            const s = row.original;
            // Simulation rows show the trajectory-level OVITO preview (the
            // sample-level image, matching the sample-detail hero); experimental
            // rows show the cached tilt-series thumbnail.
            const showMd = s.data_source === 'simulation';
            const src = showMd
              ? mdPreviewBySampleUrl(s.sample_id, s.path)
              : thumbnailUrl(s.thumbnail_path);
            const alt = showMd
              ? `OVITO preview for ${s.sample_id}`
              : `Middle tilt-series image for ${s.sample_id}`;
            return (
              <PreviewThumbnail
                alt={alt}
                clickable
                src={src}
                tooltipTitle={alt}
              />
            );
          }
        },
        {
          accessorKey: 'sample_id',
          header: 'Sample id',
          size: 220,
          // grow weight 4 vs the default 1: every column grows to fill leftover
          // width at wide screens, but sample_id takes the lion's share.
          grow: 4,
          Cell: ({ row }) => (
            <Tooltip title={row.original.sample_id}>
              <Box sx={ellipsisSx}>
                <CustomLink
                  params={{ sampleId: row.original.sample_id }}
                  to="/samples/$sampleId"
                >
                  {row.original.sample_id}
                </CustomLink>
              </Box>
            </Tooltip>
          )
        },
        { accessorKey: 'project', header: 'Project', size: 100 },
        {
          accessorKey: 'lab_name',
          header: 'Lab',
          size: 100,
          Cell: ({ cell }) => dash(cell.getValue())
        },
        {
          accessorKey: 'type',
          header: 'Type',
          size: 80,
          Cell: ({ cell }) => {
            const v = cell.getValue<string | null>();
            return (
              <Tooltip title={v ?? ''}>
                <Box sx={ellipsisSx}>{dash(v)}</Box>
              </Tooltip>
            );
          }
        },
        { accessorKey: 'n_acquisitions', header: 'Acquisitions', size: 110 },
        { accessorKey: 'n_tilt_series', header: 'Tilt', size: 80 },
        { accessorKey: 'n_tomograms', header: 'Tomograms', size: 110 }
      ],
      []
    );

    const table = useMaterialReactTable({
      columns,
      data: rows,
      getRowId: r => r.sample_id,
      positionExpandColumn: 'first',
      // Fixed column widths: 'grid' layout sizes columns from their `size` (not
      // their content), so widths stay put as you page/filter instead of jumping
      // to fit each page's values. Every column has grow weight 1 so they share
      // leftover width at wide screens; sample_id overrides to 4 to grow most.
      layoutMode: 'grid',
      enableColumnResizing: false,
      defaultColumn: { grow: 1 },
      // Pin the leading expand column to its fixed size (defaultColumn grow:1
      // would otherwise let it widen on wide screens). Its width is the anchor
      // the acquisition sub-table's fixed 64px left inset lines up against — if
      // it grows, the sub-table's thumbnail/id columns drift left of the parent's
      // (see AcquisitionsSubTable + SampleAcquisitionsTable alignment notes).
      displayColumnDefOptions: { 'mrt-row-expand': { grow: false } },
      // Clip overflowing cell text to an ellipsis so a long value can't force a
      // column wider than its fixed size. sample_id/type wrap their own content
      // (for the tooltip); this covers the plain-text columns (project, lab).
      muiTableBodyCellProps: { sx: ellipsisSx },
      muiTableHeadCellProps: {
        sx: {
          '& .Mui-TableHeadCell-Content-Wrapper': {
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis'
          }
        }
      },
      // MRT wraps the panel in <Collapse mountOnEnter unmountOnExit>, so this
      // component only mounts (and fetches its sample detail) when the row is
      // expanded — acquisitions load lazily on demand, not N fetches up front.
      // Returning a truthy element here (rather than null when collapsed) is
      // what keeps each row's expand button enabled.
      renderDetailPanel: ({ row }) => (
        <AcquisitionsSubTable
          filters={filters}
          sampleId={row.original.sample_id}
        />
      ),
      enableColumnActions: false,
      enableColumnFilters: false,
      enableGlobalFilter: false,
      enableDensityToggle: false,
      // Drop the whole internal-actions cluster (search/hide-columns/fullscreen)
      // so the top toolbar holds only pagination, mirroring the /manage tables.
      enableToolbarInternalActions: false,
      enablePagination: true,
      positionPagination: 'both',
      // The bottom toolbar already reads as separate from the body via the last
      // row's border; add the same line under the top controls so both toolbars
      // are visually set off from the table the same way. Background matches
      // the /manage tables' top toolbar (e.g. RecentlyResolvedTable).
      muiTopToolbarProps: {
        sx: {
          bgcolor: t => alpha(t.palette.primary.main, 0.12),
          borderBottom: 1,
          borderColor: 'divider'
        }
      },
      // `expanded: true` opens every detail panel; MRT still mounts each panel
      // lazily (Collapse mountOnEnter), so a fetch fires per visible page row.
      // Leave `expanded` uncontrolled (undefined) when not expanding all.
      state: {
        isLoading: loading,
        ...(expandAllDetails ? { expanded: true } : {})
      },
      initialState: {
        density: 'comfortable',
        pagination: { pageSize: 10, pageIndex: 0 }
      },
      muiTablePaperProps: {
        elevation: 0,
        sx: { border: 1, borderColor: 'divider', borderRadius: 2 }
      },
      // flexDirection:column — grid layoutMode makes this cell display:flex; the
      // panel's <Collapse> wrapper is the flex child and would shrink to its
      // content width (leaving the grey bg short of the table's right edge).
      // Column direction stretches it (cross-axis) to the full cell width.
      muiDetailPanelProps: { sx: { p: 0, flexDirection: 'column' } }
    });

    return <MaterialReactTable table={table} />;
  }
);
SamplesPortalTable.displayName = 'SamplesPortalTable';
