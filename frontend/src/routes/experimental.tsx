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

export const Route = createFileRoute('/experimental')({
  // The URL is the source of truth for filters: validate + coerce search params
  // through the shared schema so a shared/bookmarked link round-trips.
  validateSearch: (search): SamplesSearchParams =>
    samplesSearchSchema.parse(search),
  loaderDeps: ({ search }) => ({ search }),
  loader: ({ context: { queryClient }, deps: { search } }) =>
    Promise.all([
      queryClient.ensureQueryData(filtersOptionsQueryOptions),
      // Prime both the filtered list and the arm's full list (the "of N"
      // denominator), each scoped to experimental data.
      queryClient.ensureQueryData(
        samplesQueryOptions({ ...search, data_source: ['experimental'] })
      ),
      queryClient.ensureQueryData(
        samplesQueryOptions({ data_source: ['experimental'] })
      )
    ]),
  component: Experimental
});

function Experimental() {
  return (
    <SamplesBrowser
      dataSource="experimental"
      navigate={Route.useNavigate()}
      search={Route.useSearch()}
      title="Experimental data"
    />
  );
}
