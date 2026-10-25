# Classical ML Post-Evaluation Implementation Defect — Version 1.0

## Status

Resolved under the frozen implementation-defect policy. This was a correction to code that failed to match frozen feature-registry row NUM044, not a change to the registered feature set or experimental protocol.

## Preserved precursor run

`phase3_classical_ml_v1_0_20260808T210000Z`

The pre-fix run and all raw predictions remain preserved. Its formal completion status is superseded because the generic initializer assigned `0.0` to the missing `vendor_name_token_count` entity attribute.

## Frozen requirement and defect

`docs/ml_feature_registry_v1.0.csv` row NUM044 specifies “Training median; explicit entity missingness retained.” Frozen specification sections 5.4 and 7 require numeric missingness to remain missing through extraction and be imputed from the training median. The initial implementation used a name-suffix shortcut that treated every `_count` feature as an empty relationship-set count, including NUM044.

## Exact correction

The suffix shortcut was replaced by an explicit set containing only true relationship counts. No feature definition, source, family, hyperparameter, class weight, preprocessing policy, search criterion, decision rule, label, or comparator changed. A regression test asserts that both vendor-name length and token count remain numeric-missing when the vendor entity is unavailable.

## Corrected run

`phase3_classical_ml_v1_0_20260808T213000Z_auditfix1`

The complete 22-configuration validation selection and held-out evaluation were rerun. Changed raw feature cells were 46 train, 22 validation, and 28 test NUM044 values (`0.0` to missing). The selected candidate remained `hist_gradient_boosting_06`; held-out labels and probabilities were identical, so all aggregate results were unchanged. The corrected locked estimator/preprocessor hashes differ and are recorded in its model manifest.

## Scientific interpretation

The corrected run is the authoritative Phase 3 result. The identical predictions do not make the defect immaterial to protocol compliance; the rerun was required to establish that the executable pipeline faithfully implements the already frozen registry.
