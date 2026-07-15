import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Drawer,
  Grid,
  IconButton,
  Stack,
  Typography,
} from '@mui/material'
import FilterListIcon from '@mui/icons-material/FilterList'
import CloseIcon from '@mui/icons-material/Close'
import { useFiltersOptionsQuery, useSamplesQuery } from '~/utils/queryOptions'
import { useDebounce } from '~/hooks/useDebounce'
import type { SamplesSearchParams } from '~/utils/samplesSearch'
import { FilterPanel } from '~/components/landing/filters/FilterPanel'
import {
  anyAcquisitionFilterActive,
  applyGating,
  buildChips,
  computeDisabledGroups,
  filterNotices,
} from '~/components/landing/filterGating'
import { SamplesPortalTable } from '~/components/landing/SamplesPortalTable'

// The /data page spans both arms of the catalog. Unlike SamplesBrowser (which
// forces a single `data_source`), here `data_source` is a user-settable filter.
// FilterPanel consumes/emits the URL search (SamplesSearchParams) directly; the
// gating helpers (filterGating.ts) derive disabled groups, auto-select, chips,
// and notices purely from that search — no separate drawer-state object.

type NavigateFn = (opts: {
  search: (prev: SamplesSearchParams) => SamplesSearchParams
  replace?: boolean
}) => void

// Merge a patch into the search, dropping keys whose value is undefined so they
// don't linger as bare keys in the URL.
function mergePatch(
  prev: SamplesSearchParams,
  patch: Partial<SamplesSearchParams>,
): SamplesSearchParams {
  const next = { ...prev } as Record<string, unknown>
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) delete next[k]
    else next[k] = v
  }
  return next as SamplesSearchParams
}

export function AllDataBrowser(props: {
  title: string
  search: SamplesSearchParams
  navigate: NavigateFn
}) {
  const { title, search, navigate } = props
  const { data: filterOptions } = useFiltersOptionsQuery()

  // The URL updates immediately for shareability; debounce only the value that
  // drives the query (and the acquisition-subtable filtering / expand-all) so
  // typing in range fields doesn't fire a request per keystroke.
  const debouncedSearch = useDebounce(search, 300)
  const { data: samples, isFetching } = useSamplesQuery(debouncedSearch)
  const rows = samples ?? []

  // Denominator for "Showing X of Y": every sample across both arms.
  const { data: baseSamples } = useSamplesQuery({})
  const total = baseSamples?.length ?? rows.length

  const patch = (p: Partial<SamplesSearchParams>) =>
    navigate({
      search: (prev) => mergePatch(prev, applyGating(prev, p)),
      replace: true,
    })
  const clearKey = (key: string) =>
    navigate({
      search: (prev) => {
        const next = { ...prev } as Record<string, unknown>
        delete next[key]
        return next as SamplesSearchParams
      },
      replace: true,
    })
  const reset = () => navigate({ search: () => ({}), replace: true })

  const disabledGroups = computeDisabledGroups(search)
  const notices = filterNotices(search)
  const chips = buildChips(search, undefined, clearKey)
  const expandAll = anyAcquisitionFilterActive(debouncedSearch)

  // On small screens the sidebar collapses into a button that opens this drawer.
  const [filtersOpen, setFiltersOpen] = useState(false)

  const filterPanel = (
    <FilterPanel
      options={filterOptions}
      values={search}
      onChange={patch}
      disabledGroups={disabledGroups}
    />
  )

  return (
    <Grid container spacing={4}>
      <Grid
        item
        xs={12}
        md={3}
        lg={2}
        sx={{ display: { xs: 'none', md: 'block' } }}
      >
        {filterPanel}
      </Grid>

      <Grid item xs={12} md={9} lg={10}>
        <Stack spacing={2}>
          <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="center"
            spacing={2}
          >
            <Typography variant="h4" component="h1">
              {title}
            </Typography>
            <Button
              variant="outlined"
              startIcon={<FilterListIcon />}
              onClick={() => setFiltersOpen(true)}
              sx={{ display: { xs: 'inline-flex', md: 'none' }, flexShrink: 0 }}
            >
              Filters{chips.length > 0 ? ` (${chips.length})` : ''}
            </Button>
          </Stack>
          <Box>
            <Typography variant="h6">
              {rows.length.toLocaleString()} out of {total.toLocaleString()}{' '}
              total samples match the selected filters
            </Typography>
            <Stack
              direction="row"
              spacing={1}
              alignItems="center"
              flexWrap="wrap"
              useFlexGap
              sx={{ mt: 1, mb: 2 }}
            >
              <Typography variant="body2" color="text.secondary">
                Filtered by:
              </Typography>
              {chips.length > 0 ? (
                <>
                  {chips.map((c) => (
                    <Chip
                      key={c.id}
                      size="small"
                      label={c.label}
                      onDelete={c.clear}
                    />
                  ))}
                  <Chip
                    size="small"
                    color="primary"
                    label="Clear all"
                    onClick={reset}
                  />
                </>
              ) : (
                <Typography variant="body2" color="text.secondary" fontStyle="italic">
                  No filters selected
                </Typography>
              )}
            </Stack>
          </Box>

          {notices.length > 0 ? (
            <Stack spacing={1}>
              {notices.map((w) => (
                <Alert key={w} severity="warning">
                  {w}
                </Alert>
              ))}
            </Stack>
          ) : null}
        </Stack>
        {/* Table sits outside the spaced Stack so its top gap is controlled
            here rather than inheriting the Stack's 24px spacing. */}
        <Box sx={{ mt: 1 }}>
          <SamplesPortalTable
            rows={rows}
            loading={isFetching}
            filters={debouncedSearch}
            expandAllDetails={expandAll}
          />
        </Box>
      </Grid>

      <Drawer
        anchor="left"
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        sx={{ display: { md: 'none' } }}
      >
        <Box sx={{ width: 320, p: 2 }}>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
            <IconButton
              aria-label="Close filters"
              onClick={() => setFiltersOpen(false)}
            >
              <CloseIcon />
            </IconButton>
          </Box>
          {filterPanel}
        </Box>
      </Drawer>
    </Grid>
  )
}
