# 0013. Census indicator definitions and deferred methods

Status: Accepted definitions; analytical implementation pending
Date: 2026-11-12

## Context

Plan A Step 4 reviewed the 2024 ACS five-year Detailed Tables, their published geographies, exact cells and universes. Saved block-group vehicle fields were unavailable because B08201 excludes that geography. Indicator selection is distinct from spatial allocation, uncertainty estimation and scoring.

## Decision

Use 2024 ACS five-year (2020–2024 period) estimates for the initial indicators. Preserve each table's official universe and geography. These accepted definitions authorize subsequent specifications, not ingestion or analytical implementation.

| Indicator | Accepted definition and expression | Geography |
|---|---|---|
| Zero vehicle | Households without an available vehicle, using the occupied-housing-unit universe: 100 × (B25044_003E + B25044_010E) / B25044_001E. Include owners and renters. Retain the official universe label in metadata. | Block group |
| Low income | People below 200% of their applicable poverty threshold: 100 × sum(C17002_002E through C17002_007E) / C17002_001E. Accept the documented poverty-universe exclusions. | Block group |
| Age 65+ | People age 65+ divided by total population, including group quarters: 100 × sum(B01001_020E through _025E and _044E through _049E) / B01001_001E. | Block group |
| Disability | All-age civilian noninstitutionalized population with a disability: 100 × sum(B18101_004E, _007E, _010E, _013E, _016E, _019E, _023E, _026E, _029E, _032E, _035E, _038E) / B18101_001E. Accept the age-dependent Census difficulty definitions and institutionalized-population exclusion. This is broad disability prevalence, not a direct measure of walking difficulty. | Tract |
| Minority population | Everyone other than non-Hispanic White alone: 100 × (B03002_001E − B03002_003E) / B03002_001E. Descriptive label: people of color, including Hispanic/Latino residents. | Block group |
| Limited English proficiency | Persons age 5+ speaking another language at home and English less than very well, divided by all persons age 5+. Include all languages and the well, not well, and not at all responses. B16004 numerator ranges: _006E–_008E, _011E–_013E, _016E–_018E, _021E–_023E, _028E–_030E, _033E–_035E, _038E–_040E, _043E–_045E, _050E–_052E, _055E–_057E, _060E–_062E, _065E–_067E; denominator B16004_001E; multiply ratio by 100. | Block group |
| Population density | B01003_001E divided by 2024 TIGER block-group ALAND converted to square miles. Report residents per square mile. Retain as contextual information outside the initial vulnerability score. | Block group |

Poverty status excludes institutionalized people, military-group-quarter residents, college-dormitory residents and unrelated individuals under 15. The 200% threshold is a project policy selection, not a Census recommendation or fixed dollar cutoff.

Accept tract disability alongside block-group indicators, with the geography difference disclosed. Do not assign tract estimates to block groups as though independently measured there. Keep household limited-English status as an optional separate descriptive measure outside the initial index; do not add it alongside person LEP in the initial score.

Use land area for density. Keep 2020 Census block counts separate from ACS; no cross-vintage substitution or allocation is approved. Census source-native area units may be explicitly labeled as evidence: ALAND is in square meters; divide by exactly 2,589,988.110336 to obtain square miles. Calculation and output areas remain imperial. Walking speed remains exactly 2.8 mph; coordinates remain longitude/latitude degrees.

Preserve valid zeros and existing approved token normalization. Report missing or unusable estimates as unavailable. Missing or zero denominators make rates unavailable. An unavailable indicator makes the overall result incomplete; do not silently redistribute its weight.

When combining compatible complete geographic areas, sum numerators and denominators separately, then calculate the rate. Do not average geographic percentages. Compatibility requires the same indicator definition, universe, period and nonoverlapping source areas; this rule does not authorize partial-area spatial allocation.

## Deferred methodology decisions

- Partial walkshed allocation: specify and review how to estimate counts for Census polygons crossing the boundary. Do not count entire crossing polygons as exact walkshed counts. No particular allocation method or crosswalk is selected.
- Derived uncertainty: retain source margins of error; specify and validate uncertainty for derived sums, differences, percentages and spatially allocated estimates before authoritative scoring. No reliability cutoff is selected.
- Mixed-geography scoring: accepting source geography differences does not specify how tract and block-group indicators are spatially combined into a station result. Resolve that method before implementation.
- Scoring: normalization, benchmarks and weights require separate review. Equal weighting is not approved. Density's entry into a score requires separate justification; household language isolation remains optional context.

## Alternatives considered

- Tract B08201: retains a direct household table but loses block-group detail; select B25044 for the initial indicator.
- Poverty below 100% or 150%: narrower financial-constraint populations; select below 200% for the initial low-income definition.
- Disability restricted to age 5+: omits younger children with relevant difficulties; select all ages within the published universe.
- Race-only non-White complement: excludes Hispanic/Latino residents classified White alone; select the non-Hispanic-White complement.
- Adult-only LEP or household language qualification: different age/universe constructs; select persons 5+ for the initial indicator.
- Total-area density or 2020 block density: water can dilute settlement density and 2020 counts describe another period; select ACS population and 2024 land area.

## Consequences

The accepted source choices can be recorded in a future data contract and request specification. Existing ingestion remains fixed to its historical allowlist until separately authorized changes. No existing caches, fixtures or outputs are reinterpreted or regenerated. No authoritative score is established.

Plan A Step 4 research is complete. Its local 4A–4D evidence remains excluded from publication pending separate review. Plan A Step 5 is a written description of the network tile format; it does not depend on implementing deferred Census methods.

## Revisit when

The indicator's intended population changes, a later Census vintage changes table availability or definitions, observed estimates fail suitability checks, or spatial/uncertainty validation exposes a material limitation. Revisions to accepted definitions require an explicit new owner decision.

## Sources

- [2024 ACS Table List](https://www2.census.gov/programs-surveys/acs/tech_docs/table_shells/table_lists/2024_DataProductList.xlsx): publication restrictions and universes.
- [2024 ACS API table metadata](https://api.census.gov/data/2024/acs/acs5/groups.html): exact cell definitions.
- [2024 ACS Subject Definitions](https://www2.census.gov/programs-surveys/acs/tech_docs/subject_definitions/2024_ACSSubjectDefinitions.pdf): universe exclusions and age/language/disability constructs.
- [2024 TIGER technical documentation](https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2024/TGRSHP2024_TechDoc.pdf): source area fields and units.
