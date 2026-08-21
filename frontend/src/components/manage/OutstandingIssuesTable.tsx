import { useMemo, useState } from 'react';
import {
  Box,
  MenuItem,
  TablePagination,
  TextField,
  Typography,
  alpha
} from '@mui/material';
import type { IssueGroup } from '~/types';
import { useDebounce } from '~/hooks/useDebounce';
import { SectionHeader } from './SectionHeader';
import {
  type IssueFilters,
  useOutstandingIssuesQuery
} from '~/utils/queryOptions';
import {
  ExpandAllToggle,
  SampleWarningBands,
  useBandCollapse
} from './SampleWarningBands';
import { groupBySample } from './groupSampleWarnings';

// Local toolbar filters — everything except the free-text search, which is
// owned by the URL (see `q`/`onQueryChange`).
type LocalFilters = Omit<IssueFilters, 'q' | 'file_kind'>;

const PAGE_SIZE = 10;

// Distinct warning types present in the (unfiltered) data, for the dropdown.
function categoryOptions(groups: IssueGroup[]): string[] {
  const set = new Set<string>();
  for (const g of groups) {
    for (const issue of g.issues) {
      set.add(issue.category);
    }
  }
  return Array.from(set).sort();
}

export function OutstandingIssuesTable({
  q = '',
  onQueryChange
}: {
  // Free-text search. The URL is its source of truth so a filtered table is a
  // shareable link (a detail page's "view warnings" link seeds it, and typing
  // writes back through onQueryChange).
  readonly q?: string;
  readonly onQueryChange?: (q: string) => void;
}) {
  const [local, setLocal] = useState<LocalFilters>({});
  const [page, setPage] = useState(0);
  // Input + URL update on every keystroke (responsive, shareable); the query
  // only fires 300ms after typing stops (matches SamplesBrowser).
  const debouncedQ = useDebounce(q, 300);
  const filters: IssueFilters = {
    ...local,
    ...(debouncedQ ? { q: debouncedQ } : {})
  };
  const { data: rawData = [], isError } = useOutstandingIssuesQuery(filters);
  // Unfiltered denominator + dropdown options (same query key as the filtered
  // fetch when no filters are set, so they dedupe).
  const { data: allIssues = [] } = useOutstandingIssuesQuery({});
  const totalIssues = allIssues.reduce(
    (n: number, g: IssueGroup) => n + g.issues.length,
    0
  );
  const matchCount = rawData.reduce(
    (n: number, g: IssueGroup) => n + g.issues.length,
    0
  );
  const bands = useMemo(() => groupBySample(rawData), [rawData]);
  const categories = useMemo(() => categoryOptions(allIssues), [allIssues]);
  const pageBands = bands.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const collapse = useBandCollapse();

  const setFilter = <K extends keyof LocalFilters>(
    key: K,
    value: LocalFilters[K] | ''
  ) => {
    setPage(0);
    setLocal(prev => {
      const next = { ...prev };
      if (value === '' || value == null) {
        delete next[key];
      } else {
        next[key] = value as LocalFilters[K];
      }
      return next;
    });
  };

  return (
    <Box>
      <SectionHeader
        count={totalIssues}
        title="Outstanding data warnings & errors"
      />
      <Typography color="text.secondary" sx={{ mb: 2 }} variant="body1">
        {matchCount.toLocaleString()} match the selected filters
      </Typography>
      <Box
        sx={{
          p: 1.5,
          mb: 1.5,
          bgcolor: t => alpha(t.palette.primary.main, 0.12),
          border: 1,
          borderColor: 'divider',
          borderRadius: 2,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          flexWrap: 'wrap'
        }}
      >
        <ExpandAllToggle
          bandKeys={pageBands.map(b => b.key)}
          collapse={collapse}
        />
        <TextField
          onChange={e => onQueryChange?.(e.target.value)}
          placeholder="Type to filter"
          size="small"
          sx={{
            minWidth: { xs: 260, sm: 320, md: 400 },
            maxWidth: 480,
            bgcolor: 'common.white'
          }}
          value={q}
        />
        <TextField
          label="Severity"
          onChange={e =>
            setFilter('severity', e.target.value as IssueFilters['severity'])
          }
          select
          size="small"
          sx={{ minWidth: 150, bgcolor: 'common.white' }}
          value={filters.severity ?? ''}
        >
          <MenuItem value="">All severities</MenuItem>
          <MenuItem value="error">Errors only</MenuItem>
          <MenuItem value="warning">Warnings only</MenuItem>
          <MenuItem value="info">Info only</MenuItem>
        </TextField>
        <TextField
          label="Warning type"
          onChange={e => setFilter('category', e.target.value)}
          select
          size="small"
          sx={{ minWidth: 200, bgcolor: 'common.white' }}
          value={filters.category ?? ''}
        >
          <MenuItem value="">All warning types</MenuItem>
          {categories.map(c => (
            <MenuItem key={c} value={c}>
              {c.replaceAll('_', ' ')}
            </MenuItem>
          ))}
        </TextField>
        <Box sx={{ ml: 'auto' }}>
          <TablePagination
            component="div"
            count={bands.length}
            labelRowsPerPage="Samples per page"
            onPageChange={(_, p) => setPage(p)}
            page={page}
            rowsPerPage={PAGE_SIZE}
            rowsPerPageOptions={[PAGE_SIZE]}
          />
        </Box>
      </Box>
      {isError ? (
        <Typography color="error" variant="body2">
          Failed to load outstanding issues.
        </Typography>
      ) : bands.length === 0 ? (
        <Typography color="text.secondary" variant="body2">
          No outstanding warnings or errors.
        </Typography>
      ) : (
        <SampleWarningBands
          bands={pageBands}
          collapse={collapse}
          variant="outstanding"
        />
      )}
    </Box>
  );
}
