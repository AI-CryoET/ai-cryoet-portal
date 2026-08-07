import { useState } from 'react';
import { Box, Stack, TextField, Typography } from '@mui/material';
import type { ScanLogLine } from '~/types';
import { type ScanLogFilters, useScanLogsQuery } from '~/utils/queryOptions';

// HH:MM:SS in the viewer's locale, matching the wireframe's compact log stamp.
function formatLogTs(seconds: number): string {
  return new Date(seconds * 1000).toLocaleTimeString(undefined, {
    timeZoneName: 'short'
  });
}

// Per-level colour for the dark panel.
function levelColor(level: ScanLogLine['level']): string {
  switch (level) {
    case 'ERROR':
      return '#ff9b94';
    case 'WARNING':
      return '#ffd28a';
    default:
      return '#dfeaef';
  }
}

export function RunLogPanel({ scanId }: { readonly scanId: string }) {
  const [filters, setFilters] = useState<ScanLogFilters>({});
  const { data = [], isFetching, isError } = useScanLogsQuery(scanId, filters);

  const setFilter = <K extends keyof ScanLogFilters>(
    key: K,
    value: ScanLogFilters[K] | ''
  ) =>
    setFilters(prev => {
      const next = { ...prev };
      if (value === '' || value == null) {
        delete next[key];
      } else {
        next[key] = value as ScanLogFilters[K];
      }
      return next;
    });

  return (
    <Box>
      <Stack
        alignItems="center"
        direction="row"
        flexWrap="wrap"
        spacing={1.5}
        sx={{ p: 1.5, borderBottom: 1, borderColor: 'divider' }}
        useFlexGap
      >
        <TextField
          onChange={e => setFilter('q', e.target.value)}
          placeholder="Search this run's log…"
          size="small"
          sx={{ flex: 1, minWidth: 220, maxWidth: 320 }}
          value={filters.q ?? ''}
        />
      </Stack>

      <Box
        sx={{
          bgcolor: '#0e3d4b',
          color: '#dfeaef',
          p: 2,
          m: 2,
          borderRadius: 1,
          maxHeight: 360,
          overflow: 'auto',
          fontFamily: 'monospace',
          fontSize: 12.5,
          opacity: isFetching ? 0.6 : 1
        }}
      >
        {isError ? (
          <Typography
            sx={{ color: '#ff9b94', fontFamily: 'monospace' }}
            variant="body2"
          >
            Failed to load this run's log.
          </Typography>
        ) : data.length === 0 ? (
          <Typography
            sx={{ color: '#7fa6b5', fontFamily: 'monospace' }}
            variant="body2"
          >
            No log lines for this run.
          </Typography>
        ) : (
          data.map(line => (
            <Box key={line.id} sx={{ py: 0.25, whiteSpace: 'pre-wrap' }}>
              <Box component="span" sx={{ color: '#7fa6b5' }}>
                {formatLogTs(line.ts)}
              </Box>{' '}
              <Box
                component="span"
                sx={{ color: levelColor(line.level), fontWeight: 700 }}
              >
                {line.level}
              </Box>{' '}
              {line.sample_id ? (
                <Box component="span" sx={{ color: '#9fc3d6' }}>
                  {line.sample_id}:{' '}
                </Box>
              ) : null}
              <Box component="span" sx={{ color: levelColor(line.level) }}>
                {line.message}
              </Box>
            </Box>
          ))
        )}
      </Box>
    </Box>
  );
}
