# Source provenance

Copied from a locally provided src-recon source checkout (machine-specific path omitted) on
2026-11-01: models.py, classify.py, attack_surface.py, attack_path.py, demo.py and
rules/*.yaml. Original MIT license is retained in LICENSE.

The adapter does not copy the FOFA client, web server, account handling, or writers.
The imported weighted rules produce fingerprint hints and candidate investigation
paths, not verified exploits or calibrated probabilities. Typing adjustments are
recorded inline. Candidate-path quota deduplication now keys the concrete asset
instance, so two URLs or services on one host keep their own evidence references.
Classification and transition rule data remain unchanged.

Design reference only: https://github.com/projectdiscovery/httpx (MIT) informed
bounded HTTP probing, per-probe results and explicit scope. No upstream source code
is copied from that repository. Nuclei/httpx JSONL are accepted as import formats;
no external scanner executable is installed or invoked by this module.
