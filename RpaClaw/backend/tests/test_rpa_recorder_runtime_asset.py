from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_recorder_runtime_augments_generated_selectors_with_semantic_candidates():
    runtime_asset = BACKEND_ROOT / "rpa" / "vendor" / "playwright_recorder_runtime.js"
    source = runtime_asset.read_text(encoding="utf-8")

    assert "function semanticLocatorCandidates(target)" in source
    assert "const generatedCandidates = generated.selectors.map" in source
    assert "mergeLocatorCandidates(generatedCandidates, semanticLocatorCandidates(target))" in source
    assert "mergeLocatorCandidates(" in source
