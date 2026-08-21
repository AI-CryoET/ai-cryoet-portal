import { Stack } from '@mui/material';
import { useState } from 'react';
import type { FiltersOptionsOut } from '~/types';
import { GROUPS } from '~/utils/filterFields';
import type { SamplesSearchParams } from '~/utils/samplesSearch';
import { FilterGroup } from './FilterGroup';
import { FilterProperty } from './FilterProperty';
import { FilterSection } from './FilterSection';

export type FilterPanelProps = {
  readonly options: FiltersOptionsOut;
  readonly values: SamplesSearchParams; // current URL search
  readonly onChange: (patch: Partial<SamplesSearchParams>) => void;
  readonly disabledGroups?: Set<string>; // group ids disabled by gating (Phase 5 supplies)
  readonly lockedDataSource?: 'experimental' | 'simulation'; // when set, hide the data_source property
};

// ponytail: expand state is UI-only and resets on remount (acceptable — the URL
// is the source of truth for the actual filter values). Groups are keyed by
// group.id (collapsed by default); properties by field.key (options shown by
// default once their group is open).

export function FilterPanel({
  options,
  values,
  onChange,
  disabledGroups,
  lockedDataSource
}: FilterPanelProps) {
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const [collapsedProps, setCollapsedProps] = useState<Record<string, boolean>>(
    {}
  );

  const toggleGroup = (id: string) =>
    setOpenGroups(prev => ({ ...prev, [id]: !prev[id] }));

  const toggleProp = (key: string) =>
    setCollapsedProps(prev => ({ ...prev, [key]: !prev[key] }));

  const sections: Array<{ section: 'sample' | 'acquisition'; title: string }> =
    [
      { section: 'sample', title: 'Sample properties' },
      { section: 'acquisition', title: 'Acquisition properties' }
    ];

  return (
    <Stack spacing={1}>
      {sections.map(({ section, title }) => (
        <FilterSection key={section} title={title}>
          {GROUPS.filter(
            g =>
              g.section === section &&
              // On a single-arm page, drop groups that only apply to the other arm.
              !(
                lockedDataSource &&
                g.appliesTo &&
                g.appliesTo !== lockedDataSource
              )
          ).map(group => {
            const disabled = disabledGroups?.has(group.id) ?? false;
            // group.id ('general', ...) repeats across the sample and
            // acquisition sections; namespace the open-state key by section so
            // the two "General" groups toggle independently.
            const openKey = `${section}:${group.id}`;
            const fields = group.fields.filter(
              f => !(f.key === 'data_source' && lockedDataSource)
            );
            if (fields.length === 0) {
              return null;
            }
            return (
              <FilterGroup
                disabled={disabled}
                // ponytail: a disabled group renders collapsed regardless of
                // its remembered open state — MUI's `disabled` freezes the
                // toggle, so without this it'd be stuck open and its checkboxes
                // (which MUI does NOT auto-disable) would stay clickable.
                expanded={openGroups[openKey] ? !disabled : false}
                key={group.id}
                onToggle={() => toggleGroup(openKey)}
                title={group.title}
              >
                {fields.map(field => (
                  <FilterProperty
                    disabled={disabled}
                    expanded={!collapsedProps[field.key]}
                    field={field}
                    key={field.key}
                    onChange={onChange}
                    onToggle={() => toggleProp(field.key)}
                    options={options}
                    values={values}
                  />
                ))}
              </FilterGroup>
            );
          })}
        </FilterSection>
      ))}
    </Stack>
  );
}
