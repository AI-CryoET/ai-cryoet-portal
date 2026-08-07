import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FileTree, type FileNode } from '../FileTree';

const nodes: FileNode[] = [
  {
    name: 'Experimental',
    kind: 'dir',
    comment: 'data_source = experimental',
    children: [
      { name: 'sample.toml', kind: 'file', comment: 'sample-level conditions' }
    ]
  }
];

describe('FileTree', () => {
  it('renders directory names with a trailing slash and their comments', () => {
    render(<FileTree nodes={nodes} />);
    expect(screen.getByText('Experimental/')).toBeInTheDocument();
    expect(
      screen.getByText('# data_source = experimental')
    ).toBeInTheDocument();
  });

  it('renders nested file nodes (expanded by default)', () => {
    render(<FileTree nodes={nodes} />);
    expect(screen.getByText('sample.toml')).toBeInTheDocument();
    expect(screen.getByText('# sample-level conditions')).toBeInTheDocument();
  });
});
