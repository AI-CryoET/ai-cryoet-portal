import { createFileRoute } from '@tanstack/react-router';
import {
  filtersOptionsQueryOptions,
  samplesQueryOptions
} from '~/utils/queryOptions';
import {
  samplesSearchSchema,
  type SamplesSearchParams
} from '~/utils/samplesSearch';
import { SamplesBrowser } from '~/components/landing/SamplesBrowser';

export const Route = createFileRoute('/md-simulation')({
  // The URL is the source of truth for filters: validate + coerce search params
  // through the shared schema so a shared/bookmarked link round-trips.
  validateSearch: (search): SamplesSearchParams =>
    samplesSearchSchema.parse(search),
  loaderDeps: ({ search }) => ({ search }),
  loader: ({ context: { queryClient }, deps: { search } }) =>
    Promise.all([
      queryClient.ensureQueryData(filtersOptionsQueryOptions),
      // Prime both the filtered list and the arm's full list (the "of N"
      // denominator), each scoped to MD simulation data.
      queryClient.ensureQueryData(
        samplesQueryOptions({ ...search, data_source: ['simulation'] })
      ),
      queryClient.ensureQueryData(
        samplesQueryOptions({ data_source: ['simulation'] })
      )
    ]),
  component: MdSimulation
});

function MdSimulation() {
  return (
    <SamplesBrowser
      dataSource="simulation"
      navigate={Route.useNavigate()}
      search={Route.useSearch()}
      title="MD simulation data"
    />
  );
}
