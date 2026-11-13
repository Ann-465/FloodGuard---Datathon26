# Data sources and provenance

## City of San Antonio low-water crossings

- Organizer listing: `UTSA_more_data.md`
- Dataset page: https://opendata-cosagis.opendata.arcgis.com/datasets/4089adb69af14608acfb02703b1dd439_0/about
- Feature Service: https://services.arcgis.com/g1fRTDLeMgspWrYp/arcgis/rest/services/LowWaterCrossings/FeatureServer/0
- Publisher: City of San Antonio / CoSAGIS Open Data
- Retrieved: 2026-11-13
- Fields retained: `CartID`, `Name`, `OBJECTID`, `GlobalID`, longitude, latitude

`sample_locations.json` contains eight records from this official service. The
crossing identities and coordinates are real. Demonstration rainfall, visual
observation, resource availability, and urgency labels remain illustrative.

The City of San Antonio provides the geographic product as-is and disclaims accuracy,
timeliness, merchantability, and fitness warranties. See the dataset page for its
complete access and use information.

## Organizer Texas flood images

The competition README states that `Texas_Flood_Student_Data` is supplied separately
by the organizers. It is not vendored here. Houston images may test visual analysis,
but cannot update a San Antonio crossing without valid matching location metadata.

## City drainage asset layers

- Storm Inlets: https://services.arcgis.com/g1fRTDLeMgspWrYp/arcgis/rest/services/StormInlets/FeatureServer/0
- Stormwater Underground: https://services.arcgis.com/g1fRTDLeMgspWrYp/arcgis/rest/services/StormwaterUnderground/FeatureServer/0
- Storm Channels: https://services.arcgis.com/g1fRTDLeMgspWrYp/arcgis/rest/services/StormChannels/FeatureServer/0
- Publisher: City of San Antonio / CoSAGIS
- Snapshot: `real/san_antonio_crossing_features.csv`

Counts are spatial intersections within a 500 m buffer around each selected crossing.
The vulnerability proxy is
`0.35*inlet_deficit + 0.25*underground_deficit + 0.40*channel_exposure`, using fixed
caps of 150, 150, and 75 mapped features. It supports transparent ranking but is not
a measurement of pipe capacity, channel conveyance, or flood probability.

## NOAA daily precipitation

- API: https://www.ncei.noaa.gov/access/services/data/v1
- Dataset: Global Historical Climatology Network Daily Summaries (`PRCP`)
- Snapshot: `real/noaa_bexar_daily_precip_2018_2025.csv`
- Coverage: nine San Antonio-area stations, 2018-2025

`real/replay_2023-04-20.json` adds hourly Local Climatological Data from four airport
stations for a historical storm window. Times use Local Standard Time with no
daylight-saving adjustment, following NOAA documentation. Each crossing is mapped to
the nearest available gauge and the distance is retained.

## OpenFEMA NFIP claims

- API: https://www.fema.gov/api/open/v3/NfipClaims
- Filter: Bexar County FIPS `48029`, dates of loss from 2018 through 2025
- Snapshot: `real/fema_bexar_nfip_claims_2018_2025.csv`

NFIP claims provide real flood-loss dates but represent insured properties rather
than all impacts. The validation labels only claims with a positive building or
contents payment and never treats a county-level claim as evidence at a specific
crossing.

## LADI-v2 visual benchmark

- Dataset: https://huggingface.co/datasets/MITLL/LADI-v2-dataset
- Publisher: MIT Lincoln Laboratory / Civil Air Patrol
- License: CC-BY-4.0
- Use: Qwen flood/debris classification evaluation only

The test split contains 2023 disaster events and is designed to measure distribution
shift. LADI is aerial imagery, so results do not replace street-level validation and
its images are never associated with San Antonio crossings.

