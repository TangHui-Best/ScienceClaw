# F010 Assisted Asset Review And Promotion Pipeline Plan

## Goal

Build a readable asset review packet generator and a non-blocking
`candidate-lite` promotion path for newly captured RPA Harness assets.

## Architecture

Keep Review Packet generation separate from governed blocking selection. The
review layer reads existing asset evidence and runner summaries; the promotion
layer updates governance metadata; governed regression continues to treat
candidate/golden as blocking while reporting candidate-lite as warning-only
observation.

## Tasks

1. Review Packet contract:
   - Add tests for scenario identity inference, Human SOP, Evidence Summary,
     Auto Checks, Review Questions, final output, and candidate-lite
     recommendation.
   - Implement `asset_review.py` and `run_asset_review.py`.
   - Generate `review.md` under selected asset directories.

2. Candidate-lite promotion:
   - Add `candidate-lite` to governance metadata.
   - Implement `asset_promotion.py` and `run_asset_promote.py`.
   - Preserve candidate/golden expected and sensitivity review requirements.
   - Keep candidate-lite out of blocking governed selection.

3. Non-blocking observation:
   - Add candidate-lite observation to governed regression.
   - Run eligible candidate-lite assets through validation, snapshot, compiler,
     skill replay, and Stateful SOP as warning-only evidence.
   - Keep default F009 Stateful SOP eligibility unchanged for blocking
     candidate/golden assets.

4. Real asset and closeout:
   - Generate Review Packet for
     `hcap-de463b7bb608482e9b5bcdd5b78a224e`.
   - Promote it to `candidate-lite`.
   - Record RED/GREEN results, real runner output, independent reviewer status,
     residual risk, and Harness closeout in EV-010.
