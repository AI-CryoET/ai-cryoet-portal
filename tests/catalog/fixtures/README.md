Test fixtures for the catalog scanner.

The fixture tree mirrors the canonical two-arm data root:

    fixtures/
      Experimental/
        sample_chromatin/            # experimental cryoET sample (data_source=experimental)
          sample.toml
          Position_86/               # acquisition with acquisition.toml + tomogram + annotation
            TiltSeries/ts_1/         # aligned tilt series (has alignment/ artifact)
            Reconstructions/ts_1/    # tomograms/annotations grouped by tilt_series_id
              Tomograms/bp_3dctf_bin4.mrc  bp_3dctf_bin4.ome.zarr   # id = file stem
              Annotations/membrain_seg_v10.json  membrain_seg_v10.mrc  # id = shared stem
          Position_87/ ...           # Frames-only acquisition (no acquisition.toml)
      MdSimulation/
        SingleMolecule/
          sample_simulation/         # simulation sample (data_source=simulation, dataset_type=single_molecule)
            sample.toml              # dataset_type is DERIVED from the SingleMolecule/ dir, not authored
            MdRuns/
              run_001/md_run.toml    # MD-run metadata (id = folder name)
            SyntheticCryoET/
              sim_acq_01/            # acquisition nested under SyntheticCryoET/
                acquisition.toml     # references run_001 via [md_source]
                Reconstructions/Tomograms/synth_tomo_1.mrc      # flat (no tilt-series level)
                Reconstructions/Annotations/synth_ann_1.json    # id = file stem

``data_source`` and ``dataset_type`` are derived from the top-level arm
directory (``Experimental/`` vs ``MdSimulation/<SubDir>/``) by
``schema.layout.infer_arm`` during discovery; they are no longer authored in
``sample.toml``.
