import type { FileNode } from './FileTree';

// Hand-transcribed from the canonical directory layout in the repo's
// docs/data_organization.md + templates/. Not test-guarded — if that layout
// changes, update these trees to match (the zip drift guard won't catch prose).

// Block #1 — the data root's two arms (source of truth for data_source /
// dataset_type, both derived from placement, never authored).
export const dataRootTree: FileNode[] = [
  {
    name: 'data',
    kind: 'dir',
    children: [
      {
        name: 'Experimental',
        kind: 'dir',
        comment: 'data_source = experimental',
        children: [{ name: '{sample_id}', kind: 'dir', comment: '…' }]
      },
      {
        name: 'MdSimulation',
        kind: 'dir',
        comment: 'data_source = simulation',
        children: [
          {
            name: 'Bulk',
            kind: 'dir',
            comment: 'dataset_type = bulk',
            children: [{ name: '{sample_id}', kind: 'dir', comment: '…' }]
          },
          {
            name: 'SingleMolecule',
            kind: 'dir',
            comment: 'dataset_type = single_molecule',
            children: [{ name: '{sample_id}', kind: 'dir', comment: '…' }]
          },
          {
            name: 'Slab',
            kind: 'dir',
            comment: 'dataset_type = slab',
            children: [{ name: '{sample_id}', kind: 'dir', comment: '…' }]
          }
        ]
      }
    ]
  }
];

// Block #2 — experimental sample layout.
export const experimentalTree: FileNode[] = [
  {
    name: 'Experimental',
    kind: 'dir',
    children: [
      {
        name: '{sample_id}',
        kind: 'dir',
        comment: 'sample identity = directory name',
        children: [
          {
            name: 'sample.toml',
            kind: 'file',
            comment: 'sample-level conditions'
          },
          {
            name: '{acquisition_id}',
            kind: 'dir',
            comment: 'acquisition identity = directory name',
            children: [
              {
                name: 'acquisition.toml',
                kind: 'file',
                comment: 'per-acquisition params + tilt-series metadata'
              },
              {
                name: 'Frames',
                kind: 'dir',
                comment: 'raw movie frames (.eer / .tiff) + .mdoc'
              },
              { name: 'Gains', kind: 'dir', comment: 'gain reference' },
              {
                name: 'TiltSeries',
                kind: 'dir',
                children: [
                  {
                    name: '{tilt_series_id}',
                    kind: 'dir',
                    comment:
                      'one subfolder per tilt series (raw and/or aligned)',
                    children: [
                      {
                        name: 'Stack',
                        kind: 'dir',
                        comment:
                          '.mrc projection stack (+ .zarr / .rawtlt); MAY be empty'
                      },
                      {
                        name: 'Alignment',
                        kind: 'dir',
                        comment: 'MAY be empty if this is the raw tilt series',
                        children: [
                          {
                            name: 'alignment.json',
                            kind: 'file',
                            comment:
                              'affine matrix + interpolation recipe (or any other alignment data)'
                          }
                        ]
                      }
                    ]
                  }
                ]
              },
              {
                name: 'Reconstructions',
                kind: 'dir',
                children: [
                  {
                    name: '{reconstruction_alignment_id}',
                    kind: 'dir',
                    comment:
                      'a 3D alignment group; id does NOT have to match any tilt_series_id',
                    children: [
                      {
                        name: 'reconstruction.toml',
                        kind: 'file',
                        comment:
                          '3D alignment params + processing log for this group'
                      },
                      {
                        name: 'Tomograms',
                        kind: 'dir',
                        children: [
                          {
                            name: '{tomogram_id}.mrc',
                            kind: 'file',
                            comment: 'id = file name without extension'
                          },
                          { name: '{tomogram_id}.zarr', kind: 'file' }
                        ]
                      },
                      {
                        name: 'Annotations',
                        kind: 'dir',
                        comment:
                          'each annotation = a folder OR bare files sharing the {annotation_id} stem (mix allowed)',
                        children: [
                          {
                            name: '{annotation_id}',
                            kind: 'dir',
                            comment:
                              'folder form: folder name = id; holds any number of affiliated files',
                            children: [
                              { name: '{annotation_id}.star', kind: 'file' },
                              {
                                name: '{annotation_id}_aunps.png',
                                kind: 'file'
                              }
                            ]
                          },
                          {
                            name: '{annotation_id}.star',
                            kind: 'file',
                            comment:
                              'bare-file form: stem = id; any number of files, one per extension'
                          },
                          { name: '{annotation_id}.mrc / .zarr', kind: 'file' }
                        ]
                      },
                      {
                        name: 'Alignment',
                        kind: 'dir',
                        comment:
                          '3D alignment metadata for this group; MAY be empty',
                        children: [{ name: 'alignment.json', kind: 'file' }]
                      }
                    ]
                  }
                ]
              }
            ]
          }
        ]
      }
    ]
  }
];

// Block #3 — MD simulation sample layout.
export const simulationTree: FileNode[] = [
  {
    name: 'MdSimulation/{Bulk|SingleMolecule|Slab}',
    kind: 'dir',
    children: [
      {
        name: '{sample_id}',
        kind: 'dir',
        children: [
          {
            name: 'sample.toml',
            kind: 'file',
            comment: 'sample-level conditions'
          },
          {
            name: 'MdRuns',
            kind: 'dir',
            comment: 'simulation only: one subfolder per MD run',
            children: [
              {
                name: '{md_run_id}',
                kind: 'dir',
                comment: 'the folder name IS the run id',
                children: [
                  {
                    name: 'md_run.toml',
                    kind: 'file',
                    comment: 'seed, sample_time, timestep, computer, …'
                  },
                  {
                    name: 'Trajectories',
                    kind: 'dir',
                    comment: 'raw simulation output'
                  },
                  {
                    name: 'Snapshots',
                    kind: 'dir',
                    comment: 'extracted conformations (frames)'
                  }
                ]
              }
            ]
          },
          {
            name: 'SyntheticCryoET',
            kind: 'dir',
            comment: 'wraps all synthetic-cryoET acquisitions for this sample',
            children: [
              {
                name: '{acquisition_id}',
                kind: 'dir',
                comment: 'synthetic cryoET from one md_run frame',
                children: [
                  {
                    name: 'acquisition.toml',
                    kind: 'file',
                    comment: 'per-acquisition params + [md_source]'
                  },
                  {
                    name: 'TiltSeries',
                    kind: 'dir',
                    children: [
                      {
                        name: '{tilt_series_id}',
                        kind: 'dir',
                        comment: 'one subfolder per tilt series',
                        children: [
                          { name: 'Stack', kind: 'dir' },
                          { name: 'Alignment', kind: 'dir' }
                        ]
                      }
                    ]
                  },
                  {
                    name: 'Reconstructions',
                    kind: 'dir',
                    children: [
                      {
                        name: '{reconstruction_alignment_id}',
                        kind: 'dir',
                        comment:
                          'a 3D alignment group; id does NOT have to match any tilt_series_id',
                        children: [
                          {
                            name: 'reconstruction.toml',
                            kind: 'file',
                            comment:
                              '3D alignment params + processing log for this group'
                          },
                          {
                            name: 'Tomograms',
                            kind: 'dir',
                            children: [
                              {
                                name: '{tomogram_id}.mrc',
                                kind: 'file',
                                comment: 'id = file name without extension'
                              },
                              { name: '{tomogram_id}.zarr', kind: 'file' }
                            ]
                          },
                          {
                            name: 'Annotations',
                            kind: 'dir',
                            comment:
                              'each annotation = a folder OR bare files sharing the {annotation_id} stem (mix allowed)',
                            children: [
                              {
                                name: '{annotation_id}',
                                kind: 'dir',
                                comment:
                                  'folder form: folder name = id; holds any number of affiliated files',
                                children: [
                                  {
                                    name: '{annotation_id}.star',
                                    kind: 'file'
                                  },
                                  {
                                    name: '{annotation_id}_aunps.png',
                                    kind: 'file'
                                  }
                                ]
                              },
                              {
                                name: '{annotation_id}.star',
                                kind: 'file',
                                comment:
                                  'bare-file form: stem = id; any number of files, one per extension'
                              },
                              {
                                name: '{annotation_id}.mrc / .zarr',
                                kind: 'file'
                              }
                            ]
                          },
                          {
                            name: 'Alignment',
                            kind: 'dir',
                            comment:
                              '3D alignment metadata for this group; MAY be empty',
                            children: [{ name: 'alignment.json', kind: 'file' }]
                          }
                        ]
                      }
                    ]
                  }
                ]
              }
            ]
          }
        ]
      }
    ]
  }
];
