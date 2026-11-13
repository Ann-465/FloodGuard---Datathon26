# Data policy

`sample_locations.json` contains eight real low-water-crossing identifiers, names,
and coordinates retrieved from the organizer-linked City of San Antonio Feature
Service. The nearby-inlet count and mapped-asset vulnerability proxy are derived from
official City storm-inlet, underground-drainage, and channel layers within 500 m.
Criticality remains a documented neutral value until verified traffic or
emergency-route data are integrated.

Production/demo replacement order:

1. Organizer-provided `Texas_Flood_Student_Data` for visual-analysis evaluation.
2. San Antonio infrastructure sources linked by the organizers in
   `UTSA_more_data.md`.
3. Cited public datasets that fill a documented validation or coverage gap.

Historical Houston photographs must never be attached to a San Antonio risk location
without valid matching location metadata.

`real/` contains reproducible source snapshots and `metadata.json`. Refresh them
with `python scripts/fetch_real_data.py`; then regenerate real historical metrics
with `python scripts/validate_historical_rainfall.py`.

