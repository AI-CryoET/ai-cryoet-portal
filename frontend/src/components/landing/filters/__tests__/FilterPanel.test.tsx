/**
 * Render test for FilterPanel. Mounts with a small fake options/values and
 * asserts: both sections + groups render; toggling a text checkbox emits the
 * right patch; disabledGroups disables a group; lockedDataSource hides the
 * data_source property.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { FiltersOptionsOut } from '~/types';
import type { SamplesSearchParams } from '~/utils/samplesSearch';
import { FilterPanel } from '../FilterPanel';

const options: FiltersOptionsOut = {
  categorical: {
    lab_name: ['rosen', 'villa'],
    data_source: ['experimental', 'simulation']
  },
  ranges: {
    resolution: { min: 1, max: 10 }
  }
};

function setup(overrides: Partial<Parameters<typeof FilterPanel>[0]> = {}) {
  const onChange = vi.fn();
  const values: SamplesSearchParams = {};
  render(
    <FilterPanel
      options={options}
      values={values}
      onChange={onChange}
      {...overrides}
    />
  );
  return { onChange };
}

describe('FilterPanel', () => {
  it('renders both sections and group titles', () => {
    setup();
    expect(screen.getByText('Sample properties')).toBeInTheDocument();
    expect(screen.getByText('Acquisition properties')).toBeInTheDocument();
    // A sample group and an acquisition group title.
    expect(screen.getAllByText('Chromatin').length).toBeGreaterThan(0);
    expect(screen.getByText('Tilt series')).toBeInTheDocument();
  });

  it('toggling a text checkbox emits an array patch, and unchecking drops the key', async () => {
    const { onChange } = setup();
    // Open the sample "General" group (collapsed by default); its properties'
    // options are expanded once the group opens. Both sections have a "General"
    // group — the sample one is first in document order.
    await userEvent.click(
      screen.getAllByRole('button', { name: /expand all general filters/i })[0]
    );
    await userEvent.click(screen.getByRole('checkbox', { name: 'rosen' }));
    expect(onChange).toHaveBeenCalledWith({ lab_name: ['rosen'] });
  });

  it('unchecking the only selected option emits undefined', async () => {
    const onChange = vi.fn();
    render(
      <FilterPanel
        options={options}
        // SamplesSearchParams' registry fields are built dynamically from the
        // zod schema, so tsc can't see lab_name statically — cast for the test.
        values={{ lab_name: ['rosen'] } as SamplesSearchParams}
        onChange={onChange}
      />
    );
    await userEvent.click(
      screen.getAllByRole('button', { name: /expand all general filters/i })[0]
    );
    await userEvent.click(screen.getByRole('checkbox', { name: 'rosen' }));
    expect(onChange).toHaveBeenCalledWith({ lab_name: undefined });
  });

  it('lockedDataSource hides the data_source property', async () => {
    setup({ lockedDataSource: 'experimental' });
    // Open the sample "General" group to reveal its properties.
    await userEvent.click(
      screen.getAllByRole('button', { name: /expand all general filters/i })[0]
    );
    expect(
      screen.queryByRole('button', { name: 'Data source' })
    ).not.toBeInTheDocument();
    // Other general fields still present.
    expect(screen.getByRole('button', { name: 'Lab' })).toBeInTheDocument();
  });

  it('disabledGroups disables the group control, hiding its properties', () => {
    setup({ disabledGroups: new Set(['chromatin']) });
    // The Chromatin group control is disabled and can't be opened, so its
    // properties stay hidden.
    const ctrl = screen.getByRole('button', {
      name: /expand all chromatin filters/i
    });
    expect(ctrl).toBeDisabled();
    expect(
      screen.queryByRole('button', { name: 'Substrate' })
    ).not.toBeInTheDocument();
  });
});
