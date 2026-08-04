import pytest
from pydantic import ValidationError
from schema.schema import ReconstructionFile, SampleRecord, Sample


def test_reconstruction_file_parses_full_block():
    rf = ReconstructionFile.model_validate({
        "reconstruction_alignment": {"alignment_software": "AreTomo3"},
        "raw_tomogram": [{"id": "ctf", "pipeline": "backprojection"}],
        "post_processed_tomogram": [{"id": "even"}],
        "annotation": [{"id": "Missalignment", "type": "membrane_segmentation"}],
    })
    assert rf.reconstruction_alignment.alignment_software == "AreTomo3"
    assert rf.raw_tomogram[0].tomogram_id == "ctf"
    assert rf.post_processed_tomogram[0].tomogram_id == "even"
    assert rf.annotation[0].annotation_id == "Missalignment"


def test_reconstruction_file_flags_duplicate_tomogram_ids():
    with pytest.raises(ValidationError):
        ReconstructionFile.model_validate({
            "reconstruction_alignment": {},
            "raw_tomogram": [{"id": "ctf"}, {"id": "ctf"}],
        })


def test_sample_record_holds_reconstructions_map():
    rec = SampleRecord(sample=Sample.model_validate({"id": "s1", "project": "chromatin"}))
    assert rec.reconstructions == {}


def test_leaf_models_carry_the_group_id():
    """A tomogram/annotation records which alignment group it belongs to, so
    two groups can hold the same file stem without colliding in storage."""
    from schema import Annotation, PostProcessedTomogram, RawTomogram

    raw = RawTomogram.model_validate(
        {"id": "denoised", "reconstruction_alignment_id": "recon_1"}
    )
    assert raw.reconstruction_alignment_id == "recon_1"
    post = PostProcessedTomogram.model_validate(
        {"id": "denoised", "reconstruction_alignment_id": "recon_2"}
    )
    assert post.reconstruction_alignment_id == "recon_2"
    ann = Annotation.model_validate(
        {"id": "seg", "reconstruction_alignment_id": "recon_1"}
    )
    assert ann.reconstruction_alignment_id == "recon_1"


def test_leaf_group_id_defaults_to_none():
    """It is path-injected, never authored, so an authored block omits it."""
    from schema import RawTomogram

    assert RawTomogram.model_validate({"id": "denoised"}).reconstruction_alignment_id is None
