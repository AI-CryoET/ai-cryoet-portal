import { useMemo, useState } from 'react';
import { Box, TablePagination, Typography } from '@mui/material';
import { useRecentlyResolvedQuery } from '~/utils/queryOptions';
import {
  ExpandAllToggle,
  SampleWarningBands,
  useBandCollapse
} from './SampleWarningBands';
import { groupBySample } from './groupSampleWarnings';

const PAGE_SIZE = 10;

export function RecentlyResolvedTable({
  withinHours = 24
}: {
  readonly withinHours?: number;
}) {
  const { data: rawData } = useRecentlyResolvedQuery(withinHours);
  const bands = useMemo(() => groupBySample(rawData), [rawData]);
  const [page, setPage] = useState(0);
  const pageBands = bands.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const collapse = useBandCollapse();

  if (bands.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        Nothing resolved in the last 24 hours.
      </Typography>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center' }}>
        <ExpandAllToggle
          bandKeys={pageBands.map(b => b.key)}
          collapse={collapse}
        />
        {bands.length > PAGE_SIZE ? (
          <TablePagination
            component="div"
            count={bands.length}
            labelRowsPerPage="Samples per page"
            onPageChange={(_, p) => setPage(p)}
            page={page}
            rowsPerPage={PAGE_SIZE}
            rowsPerPageOptions={[PAGE_SIZE]}
            sx={{ ml: 'auto' }}
          />
        ) : null}
      </Box>
      <SampleWarningBands
        bands={pageBands}
        collapse={collapse}
        variant="resolved"
      />
    </Box>
  );
}
