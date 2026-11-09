"""Fixed identifiers for the proposed Task 5.4 Census sample.

These values describe an experimental proposal. They become usable by the
pipeline only when a local run configuration records explicit acceptance.
"""

SPECIFICATION_VERSION = "census-sample-proposal-1"
CONFIGURATION_VERSION = "census-sample-1"
NORMALIZATION_VERSION = "acs-quartet-normalization-proposal-1"
DATASET_PATH = "2024/acs/acs5"
STATE_FIPS = "08"
COUNTY_FIPS = ("031", "073")

VARIABLES = {
    "B01003_001": {
        "concept": "Total Population",
        "estimate_label": "Estimate!!Total",
        "role": "population_count",
    },
    "B08201_001": {
        "concept": "Household Size by Vehicles Available",
        "estimate_label": "Estimate!!Total:",
        "role": "household_denominator",
    },
    "B08201_002": {
        "concept": "Household Size by Vehicles Available",
        "estimate_label": "Estimate!!Total:!!No vehicle available",
        "role": "no_vehicle_household_numerator",
    },
}

VARIABLE_FIELDS = tuple(
    f"{cell}{suffix}"
    for cell in VARIABLES
    for suffix in ("E", "EA", "M", "MA")
)
ACS_REQUEST_FIELDS = ("NAME", *VARIABLE_FIELDS)
GEOGRAPHY_FIELDS = ("state", "county", "tract", "block group")
