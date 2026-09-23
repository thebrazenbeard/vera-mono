# vera-mono

Self-contained Vera monorepo.

This repository is the integration target for a Vera runtime whose implementation lives inside one repository. External repositories may be inspected as research/provenance donors, but runtime implementation is absorbed here rather than invoked through Git submodules or cross-repository orchestration.

## Bootstrap

- seed source: `thebrazenbeard/vera@87aa888cb7543875ffa11c9c7a1eb9e5b60c35cf`
- absorption candidate: `thebrazenbeard/vera#200@078d2d7242384c58676305d47654406713e599cf`
- target rule: no Git submodules
- target rule: no runtime dependency on sibling GitHub repositories
- target rule: preserve exact donor provenance for absorbed mechanisms
- target rule: providers such as databases/model APIs remain external infrastructure, not source-code dependencies

The repository is being built incrementally. Presence of a donor reference does not make that donor a runtime dependency.
