import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SampleSearchField } from '../SampleSearchField';

describe('SampleSearchField', () => {
  it('shows the current value', () => {
    render(<SampleSearchField value="tomo-777" onChange={() => {}} />);
    expect(screen.getByRole('textbox')).toHaveValue('tomo-777');
  });

  it('calls onChange with the typed value', () => {
    const onChange = vi.fn();
    render(<SampleSearchField value="" onChange={onChange} />);
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'acq-100' }
    });
    expect(onChange).toHaveBeenCalledWith('acq-100');
  });
});
