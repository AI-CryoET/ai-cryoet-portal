import { memo, useEffect, useMemo, useState } from 'react';
import { alpha, Box, Tooltip } from '@mui/material';
import {
  MaterialReactTable,
  MRT_TablePagination,
  useMaterialReactTable,
  type MRT_ColumnDef
} from 'material-react-table';
import type { SampleSummary } from '~/types';
import type { SamplesSearchParams } from '~/utils/samplesSearch';
import { CustomLink } from '~/components/CustomLink';
import {
  PreviewThumbnail,
  thumbnailUrl,
  mdPreviewUrl
} from '~/components/common/Thumbnail';
import { AcquisitionsSubTable } from './AcquisitionsSubTable';
import { SampleSearchField } from './SampleSearchField';
import { hasDescendantMatch } from './samplesMatchDisplay';

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
    // Free-text id search rendered in the table's top toolbar (like the
    // /manage warnings table). `searchValue` is the immediate URL `q` so typing
    // is responsive; `onSearchChange` MUST be stable (useCallback in the
    // browser) so it doesn't bust the memo on every render — otherwise filter
    // typing would re-render the table again (the lag this memo prevents).
    readonly searchValue?: string;
    readonly onSearchChange?: (q: string) => void;
  }) => {
    const {
      rows,
      loading,
      filters,
      expandAllDetails,
      searchValue,
      onSearchChange
    } = props;

    // Rows whose match is below sample level (acquisition/tomogram/annotation)
    // auto-expand so the hit is visible; a sample-id-only match does not. Kept
    // as controlled state (not a literal `expanded: true`) so the user's manual
    // toggle keeps working afterward — it's only reset when a new `rows` array
    // arrives (new search/page), never on every render.
    const [expanded, setExpanded] = useState<Record<string, boolean>>({});
    useEffect(() => {
      const defaults: Record<string, boolean> = {};
      for (const r of rows) {
        if (hasDescendantMatch(r.matches)) {
          defaults[r.sample_id] = true;
        }
      }
      setExpanded(defaults);
    }, [rows]);

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
              ? mdPreviewUrl(s.md_preview_path)
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
          matches={row.original.matches}
          sampleId={row.original.sample_id}
        />
      ),
      enableColumnActions: false,
      enableColumnFilters: false,
      enableGlobalFilter: false,
      enableDensityToggle: false,
      // Drop the whole internal-actions cluster (search/hide-columns/fullscreen);
      // the custom top toolbar below owns the id-search field + pagination,
      // mirroring the /manage warnings table (OutstandingIssuesTable).
      enableToolbarInternalActions: false,
      enablePagination: true,
      // Pagination lives in the default bottom toolbar and is also rendered in
      // the custom top toolbar below (was 'both' with the stock top toolbar).
      positionPagination: 'bottom',
      // Custom top toolbar: id-search field left, pagination right. Background +
      // divider match the /manage tables' top toolbar (e.g. RecentlyResolvedTable).
      renderTopToolbar: ({ table }) => (
        <Box
          sx={{
            p: 1.5,
            bgcolor: t => alpha(t.palette.primary.main, 0.12),
            borderBottom: 1,
            borderColor: 'divider',
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            flexWrap: 'wrap'
          }}
        >
          {onSearchChange ? (
            <SampleSearchField
              onChange={onSearchChange}
              value={searchValue ?? ''}
            />
          ) : null}
          {/* ml:auto pushes pagination to the right edge; when the row wraps on
              small screens the search field takes its own line above it. */}
          <Box sx={{ ml: 'auto', alignSelf: 'flex-end' }}>
            <MRT_TablePagination table={table} />
          </Box>
        </Box>
      ),
      // `expanded: true` opens every detail panel; MRT still mounts each panel
      // lazily (Collapse mountOnEnter), so a fetch fires per visible page row.
      // Acquisition-filter mode forces every row open (unrelated to search).
      // Otherwise `expanded` is the per-row state above, seeded from matches but
      // freely toggled afterward via onExpandedChange.
      state: {
        isLoading: loading,
        expanded: expandAllDetails ? true : expanded
      },
      onExpandedChange: updater => {
        setExpanded(prev => {
          const next = typeof updater === 'function' ? updater(prev) : updater;
          // `true` (expand-all) is never produced by a row's own toggle click —
          // the internal expand-all control is disabled — but guard it anyway
          // since MRT's type allows it.
          return next === true ? prev : next;
        });
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
