# Census sample specification

Version: `census-sample-proposal-1`. Status: accepted for the local experiment on November 5, 2026. Gate 5A is accepted by developer report. This document specifies Task 5.5; it does not authorize authoritative indicators, scores, source repinning or publication.

## Dataset and sample

Use `https://api.census.gov/data/2024/acs/acs5`: 2020–2024 ACS five-year **Detailed Tables**, at standard block-group geography (summary level 150). These are period estimates, not a 2024 population census. Proposed county allowlist: Colorado state `08`, Denver `031` and Lincoln `073`. Fetch complete block-group sets for each county. Lincoln is a rural geography/allocation diagnostic, not an assertion that the existing Denver routing graph covers it. Adding counties requires an explicit configuration change and review; no automatic statewide expansion.

Keep the supplied 2020 tabulation-block `POP20` and `HOUSING20` counts in a separate vintage. Housing units include vacant units; ACS households describe occupied housing units. They are not interchangeable denominators. Do not force 2020 totals to agree with ACS estimates, infer growth from disagreement, or substitute one vintage for missing values in another.

The initial indicator set deliberately contains three additive cells. Poverty, age, disability, employment and income indicators remain out of this sample. Median income is not requested or spatially averaged.

## Exact variables

| Cell | Census concept | Exact estimate label | Universe | Role |
|---|---|---|---|---|
| `B01003_001` | Total Population | `Estimate!!Total` | Total population | Person-count estimate; no rate denominator |
| `B08201_001` | Household Size by Vehicles Available | `Estimate!!Total:` | Households | Household count and denominator for no-vehicle share |
| `B08201_002` | Household Size by Vehicles Available | `Estimate!!Total:!!No vehicle available` | Households | No-vehicle household numerator |

For **each** cell request all four fields: suffix `E` (estimate), `EA` (estimate annotation), `M` (margin of error), and `MA` (MOE annotation). Thus the required set is:

```text
B01003_001E,B01003_001EA,B01003_001M,B01003_001MA,
B08201_001E,B08201_001EA,B08201_001M,B08201_001MA,
B08201_002E,B08201_002EA,B08201_002M,B08201_002MA
```

E/M fields have API predicate type `int`; EA/MA fields are strings. The corresponding label prefixes are `Estimate`, `Annotation of Estimate`, `Margin of Error`, and `Annotation of Margin of Error`, followed by the identical `!!Total` / `!!Total:` / `!!Total:!!No vehicle available` suffix above. Validate these definitions against a saved, dataset-specific metadata response before ingestion; changed/missing labels, types or attributes require review. A matching local catalog entry alone does not establish its year or prove observations were retrieved.

The proposed no-vehicle share is `100 * sum(valid allocated B08201_002E) / sum(valid allocated B08201_001E)`. Use paired numerator/denominator coverage and the same allocation weights. Never divide by persons or housing units, average block-group percentages, or compute a rate with a zero/missing denominator. Return null with a reason. If valid numeric numerator exceeds its denominator, preserve raw values and flag the inconsistency; do not clamp or silently repair.

## Missingness and uncertainty

Preserve raw E/EA/M/MA strings and normalized values separately. Parse null/blank first, annotations second, sentinels third, ordinary numeric counts last. A zero count is valid. A negative value is never a count. Recognize these numeric sentinels, including equivalent decimal spellings: `-999999999` (insufficient sample/display unavailable), `-888888888` (not applicable/available), `-666666666` (estimate not computable), `-555555555` (controlled MOE), `-333333333` (open-ended median interval), `-222222222` (MOE not computable). Normalize the affected number to null with its reason; retain the raw token. Unknown negative values or malformed positive values are errors, not missing-data substitutions.

Retain nonempty annotations as the displayed qualification instead of showing the numeric field alone. `N`, `(X)`, `-`, `**`, `***`, `*****`, `+`, `*` and `c` are not numbers. In this count-only prototype, annotated **estimates** are excluded from arithmetic until their meaning is explicitly supported; unknown annotation codes fail normalization. An annotated or missing MOE does not erase an otherwise valid estimate: mark uncertainty unavailable/controlled as appropriate. Do not turn a controlled MOE into zero. Unknown sentinel/annotation combinations require review.

Retain published source MOEs and identify their confidence level from the dataset documentation (ACS published MOEs use 90% confidence). For allocated, combined or ratio results, set `derived_uncertainty = not_quantified`. Do not scale/sum/root-sum-square MOEs, invent a derived confidence interval, or run significance tests in this experiment. Spatial allocation error is additional to sampling error. No claim of precise small-area population follows from a visually detailed polygon.

## Geography and joins

The local block-group archive is `tl_2024_08_bg.zip`, observed EPSG:4269, 4,058 features, with `STATEFP`, `COUNTYFP`, `TRACTCE`, `BLKGRPCE`, `GEOID`, `GEOIDFQ`, `ALAND`, `AWATER`. The block archive is `tl_2020_08_tabblock20.zip`, observed EPSG:4269, 140,345 features, with `GEOID20`, `POP20`, `HOUSING20`, `ALAND20`, `AWATER20` and geographic component fields. These are metadata observations, not new geometry/join validation.

Build ACS block-group GEOID as string `state(2) + county(3) + tract(6) + block group(1)`. For example `08 + 031 + 000100 + 1 = 080310001001`. Enforce decimal-string widths on the original components; do not numeric-convert or pad a malformed incoming field. Check each shape's `GEOID` against its components and reject duplicate/null keys. Join **one ACS row to one full 2024 block-group feature** for every allowlisted county. Compare the complete two key sets before any geographic sample clipping. Missing-on-either-side IDs fail the complete-join claim and require a diagnostic exception decision, rather than an inner join that hides them.

The ACS geography documentation identifies 2020-based statistical block groups, with possible complementary boundary changes; TIGER documentation also warns that current block groups need not preserve old block-number relationships. Therefore a 2020 block's first 12 GEOID characters are only a candidate historic parent. Do not treat that prefix as a verified cross-vintage join. Task 5.5 outputs independent 2020 blocks and joined 2024 block groups. Task 5.6 initially compares allocation at each original geography; ACS redistribution using 2020 block weights is deferred pending an independently reviewed spatial crosswalk.

Read full polygons for the allowed counties. For later station-area selection, retain the complete polygon of every intersecting unit, including multipart pieces and holes; never replace the allocation denominator with its clipped study-area geometry. EPSG:4269 is the observed source CRS, not EPSG:4326. Record explicit source-to-target transformations and axis order.

## Provenance and source status

Local source identities authorized for this prototype on November 5, 2026:

| File | Bytes | SHA-256 |
|---|---:|---|
| `tl_2020_08_tabblock20.zip` | 218525462 | `708f5ecde530a9e8d6ed10be4cfbf6d9bac3fcdf26498b7546973503de38d4b4` |
| `tl_2024_08_bg.zip` | 13503201 | `fe719ce2e62b05dc963a6864e2f7442cdabe3211532d2fac73813b5fedf505e1` |
| `variables.json` | 10508565 | `f689926f9a34944a7d5e66f78e5eb47ae801dc06e7b09cd2b724950a7546e4a8` |

Download dates and receipts for these local files remain unknown. Official reference locations are `https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/` and `https://www2.census.gov/geo/tiger/TIGER2024/BG/`; these reference locations are not proof that the local bytes were downloaded there. The developer accepted the Task 5.4 experiment and these local Census files on November 5, 2026. The ignored approved run configuration pins these exact hashes; download dates and receipts remain unknown.

Record source product/year, observed hash, provenance gaps, retrieved metadata URL/date and attribution: U.S. Census Bureau, 2020 Census tabulation blocks; 2024 TIGER/Line block groups; 2020–2024 ACS five-year Detailed Tables. Census data are federal public data; preserve the Census suggested citation and no-warranty notice. No Census logo/endorsement or redistribution approval for mixed OSM/client products is implied. Keep raw inputs and local derived packets ignored.

## Verification sources

Reviewed November 5, 2026. These are metadata/documentation checks, not successful live observation requests.

- [2024 ACS five-year dataset](https://www.census.gov/data/developers/data-sets/acs-5year/2024.html) and [API geography hierarchy](https://api.census.gov/data/2024/acs/acs5/geography.html).
- [B01003 fields](https://api.census.gov/data/2024/acs/acs5/groups/B01003.html) and [B08201 fields](https://api.census.gov/data/2024/acs/acs5/groups/B08201.html). All three selected local catalog entries match the published estimate labels and quartet attributes; local catalog vintage remains unverified.
- [2024 ACS subject definitions](https://www2.census.gov/programs-surveys/acs/tech_docs/subject_definitions/2024_ACSSubjectDefinitions.pdf), [Census B08201 household universe](https://data.census.gov/table/ACSDT1Y2024.B08201?g=040XX00US06&q=household+size). The latter is same-year one-year table universe evidence, not an observation source for this five-year sample.
- [Estimate/annotation conventions](https://www.census.gov/data/developers/data-sets/acs-1year/data-notes.html), cross-product variable conventions; snapshot expected codes and fail unknowns rather than assuming a sentinel is a real count.
- [2024 ACS boundary vintage](https://www.census.gov/programs-surveys/acs/geography-acs/geography-boundaries-by-year.2024.html) and [2024 TIGER technical documentation](https://www2.census.gov/geo/pdfs/maps-data/data/tiger/tgrshp2024/TGRSHP2024_TechDoc.pdf).
- [Current ACS API examples/key requirement](https://api.census.gov/data/2024/acs/acs5/examples.html): an API key is now required for data queries; old advice about unauthenticated daily quotas is not the plan.

Published uncertainty reference: [2020–2024 ACS accuracy documentation](https://www2.census.gov/programs-surveys/acs/tech_docs/accuracy/MultiyearACSAccuracyofData2024.pdf). For modified TIGER-derived public products, retain the technical documentation's conspicuous distinction from an original Census product and its attribution/trademark guidance; no mixed-product release is authorized here.
