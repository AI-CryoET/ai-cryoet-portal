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

// Each browse page is scoped to a single `data_source` arm of the catalog
// (Experimental/ vs MdSimulation/). The value is forced into every samples
// query here and `data_source` is locked in the panel (the property is hidden
// and the opposite arm's groups are disabled) — a page only ever shows its arm.
export type DataSource = 'experimental' | 'simulation'

type NavigateFn = (opts: {
  search: (prev: SamplesSearchParams) => SamplesSearchParams
  replace?: boolean
}) => void

// Merge a patch into the search, dropping undefined-valued keys.
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

export function SamplesBrowser(props: {
  title: string
  dataSource: DataSource
  search: SamplesSearchParams
  navigate: NavigateFn
}) {
  const { title, dataSource, search, navigate } = props
  const { data: filterOptions } = useFiltersOptionsQuery()

  // The URL updates immediately on every change; debounce only the value that
  // drives the query (and subtable filtering / expand-all). `data_source` is
  // forced to this arm regardless of the URL.
  const debouncedSearch = useDebounce(search, 300)
  const armScoped = { ...debouncedSearch, data_source: [dataSource] }
  const { data: samples, isFetching } = useSamplesQuery(armScoped)
  const rows = samples ?? []

  // Denominator for "Showing X of Y": all samples in this arm, ignoring filters.
  const { data: baseSamples } = useSamplesQuery({ data_source: [dataSource] })
  const total = baseSamples?.length ?? rows.length

  const patch = (p: Partial<SamplesSearchParams>) =>
    navigate({
      search: (prev) => mergePatch(prev, applyGating(prev, p, dataSource)),
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

  const disabledGroups = computeDisabledGroups(search, dataSource)
  const notices = filterNotices(search, dataSource)
  const chips = buildChips(search, dataSource, clearKey)
  // Pass the arm-forced data_source so the subtable predicate sees the same
  // committed filter set the server query used.
  const expandAll = anyAcquisitionFilterActive(debouncedSearch)

  // On small screens the sidebar collapses into a button that opens this drawer.
  const [filtersOpen, setFiltersOpen] = useState(false)

  const filterPanel = (
    <FilterPanel
      options={filterOptions}
      values={search}
      onChange={patch}
      disabledGroups={disabledGroups}
      lockedDataSource={dataSource}
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
        <Box sx={{ mt: 0 }}>
          <SamplesPortalTable
            rows={rows}
            loading={isFetching}
            filters={armScoped}
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
