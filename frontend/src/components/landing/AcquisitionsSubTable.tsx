import { useMemo } from 'react';
import { Box, Typography } from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { sampleDetailQueryOptions } from '~/utils/queryOptions';
import { matchAcquisition } from '~/utils/acquisitionMatch';
import type { SamplesSearchParams } from '~/utils/samplesSearch';
import { SampleAcquisitionsTable } from '~/components/samples/SampleAcquisitionsTable';

export function AcquisitionsSubTable({
  sampleId,
  filters
}: {
  readonly sampleId: string;
  readonly filters?: SamplesSearchParams;
}) {
  const { data, isLoading, isError } = useQuery(
    sampleDetailQueryOptions(sampleId)
  );

  const all = data?.acquisitions ?? [];
  const filtered = useMemo(
    () => (filters ? all.filter(a => matchAcquisition(a, filters)) : all),
    [all, filters]
  );

  // The server only returns a sample when ≥1 acquisition matched, so a filtered
  // result of 0 while the sample has acquisitions means the client/server
  // predicates have drifted — surface it visibly instead of an empty table.
  const drifted =
    !!filters && !isLoading && all.length > 0 && filtered.length === 0;

  return (
    // pl offsets the nested table by the parent's leading expand column so its
    // thumbnail + Acquisition-id columns line up under the parent's thumbnail +
    // Sample-id columns. 64px = expandCol(60) + comfy-display-pad(12) −
    // compact-display-pad(8); paired with the 84px thumbnail column in
    // SampleAcquisitionsTable (see the alignment note there).
    // width:100% — filling the cell makes the grey span the full sample-table width.
    <Box sx={{ p: 2, pl: '64px', bgcolor: 'action.hover', width: '100%' }}>
      <Typography color="text.secondary" variant="overline">
        Acquisitions{filters ? ` (${filtered.length} of ${all.length})` : ''}
      </Typography>
      {isError ? (
        <Typography color="error" sx={{ mt: 1 }} variant="body2">
          Failed to load acquisitions.
        </Typography>
      ) : (
        <Box sx={{ mt: 1 }}>
          {drifted ? (
            <Typography color="warning.main" sx={{ mb: 1 }} variant="body2">
              ⚠ Filter mismatch: server matched this sample but no acquisition
              matched client-side (predicate drift — see acquisitionMatch.ts).
            </Typography>
          ) : null}
          <SampleAcquisitionsTable
            acquisitions={filtered}
            compact
            isLoading={isLoading}
            sampleId={sampleId}
          />
        </Box>
      )}
    </Box>
  );
}
