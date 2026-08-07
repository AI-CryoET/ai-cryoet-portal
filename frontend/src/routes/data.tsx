import { createFileRoute } from '@tanstack/react-router';
import {
  filtersOptionsQueryOptions,
  samplesQueryOptions
} from '~/utils/queryOptions';
import {
  samplesSearchSchema,
  type SamplesSearchParams
} from '~/utils/samplesSearch';
import { AllDataBrowser } from '~/components/landing/AllDataBrowser';

export const Route = createFileRoute('/data')({
  // The URL is the source of truth for filters: validate + coerce search params
  // through the shared schema so a shared/bookmarked link round-trips.
  validateSearch: (search): SamplesSearchParams =>
    samplesSearchSchema.parse(search),
  loaderDeps: ({ search }) => ({ search }),
  loader: ({ context: { queryClient }, deps: { search } }) =>
    Promise.all([
      queryClient.ensureQueryData(filtersOptionsQueryOptions),
      // Prime both the filtered list (honouring the URL's data_source, if any)
      // and the unfiltered all-arms list (the "of N" denominator).
      queryClient.ensureQueryData(samplesQueryOptions(search)),
      queryClient.ensureQueryData(samplesQueryOptions({}))
    ]),
  component: AllData
});

function AllData() {
  return (
    <AllDataBrowser
      navigate={Route.useNavigate()}
      search={Route.useSearch()}
      title="All data"
    />
  );
}
