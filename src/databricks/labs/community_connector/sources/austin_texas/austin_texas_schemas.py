"""Schema, metadata, and constants for the Austin, Texas (Socrata SODA) connector.

The connector's scope is a single Socrata dataset — "Green Building Ratings
Aggregate" (resource id ``dpvb-c5fy``) exposed at
``https://data.austintexas.gov/resource/dpvb-c5fy.json``.

The schema below is transcribed from the dataset's column metadata
(``GET /api/views/dpvb-c5fy.json``) and cross-checked against live row data.
It is hard-coded rather than fetched at runtime because it is small, stable,
and the metadata endpoint returns column definitions in a shape that would
require its own parsing/mapping layer for no practical benefit here.

Type-mapping notes (Socrata quirks — see the API doc):
  * Socrata ``number`` columns serialize as JSON *strings* (arbitrary-precision
    decimals), e.g. ``"2543.30"``. They are declared here as ``DoubleType``;
    the framework's ``parse_value`` coerces the string to a float.
  * ``pv_generation_mwh_`` is typed ``text`` in the source metadata (not
    ``number``) despite holding numeric-looking strings — declared ``StringType``.
  * ``calendar_date`` columns are floating timestamps with no timezone offset
    (e.g. ``"2006-10-01T00:00:00.000"``) — declared ``TimestampType``.
  * Rows omit a column key entirely when the cell is empty (sparse rows), so all
    non-key columns are nullable; the framework maps missing keys to ``None``.
"""

from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# Portal host and dataset identity.  The four-by-four resource id is Socrata's
# permanent identifier (stable across dataset renames), so it is safe to
# hard-code rather than the human-readable slug.
BASE_URL = "https://data.austintexas.gov"
RESOURCE_ID = "dpvb-c5fy"
TABLE_NAME = "green_building_ratings_aggregate"

# The dataset exposes no row-identifier column; a composite business key of
# (fiscal_year, class) uniquely identifies every aggregate row.
PRIMARY_KEYS = ["fiscal_year", "class"]

# Retry policy for Socrata throttling (429) and transient server errors.
# Socrata does not document a numeric rate limit and reserves the right to
# throttle even token-bearing requests it deems abusive, so retry regardless
# of whether an app token is supplied.
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0  # seconds; doubled after each retry

# Default per-request page size for the snapshot read.  The dataset is tiny
# (~57 rows) so a single page fetches everything, but the connector pages
# defensively so the same code path keeps working if the row count grows.
DEFAULT_PAGE_SIZE = 1000

# HTTP request timeout (seconds).  Always set explicitly so a slow/hung source
# fails fast instead of blocking the connector indefinitely.
REQUEST_TIMEOUT = 30

# Deterministic sort so ``$limit``/``$offset`` paging is stable across pages.
SNAPSHOT_ORDER = "fiscal_year,class"

# Hard-coded schema for green_building_ratings_aggregate (22 columns).
GREEN_BUILDING_SCHEMA = StructType(
    [
        # Composite business key — always present in every row.
        StructField("fiscal_year", StringType(), nullable=False),
        StructField("class", StringType(), nullable=False),
        # Numeric measures — serialized as JSON strings by Socrata, coerced to
        # double by the framework.
        StructField("number_of_projects_aegb_rated", DoubleType(), nullable=True),
        StructField("number_of_projects_leed_reported", DoubleType(), nullable=True),
        StructField("total_square_footage_aegb_rated_projects", DoubleType(), nullable=True),
        StructField("number_of_residential_units_aegb_rated", DoubleType(), nullable=True),
        StructField("number_of_smart_housing_units_aegb_rated", DoubleType(), nullable=True),
        StructField("estimated_energy_savings_mbtu", DoubleType(), nullable=True),
        StructField("estimated_demand_savings_kw", DoubleType(), nullable=True),
        StructField("estimated_electric_energy_savings_kwh", DoubleType(), nullable=True),
        # Quirk: typed ``text`` in the source metadata, not ``number``.
        StructField("pv_generation_mwh_", StringType(), nullable=True),
        StructField("gas_savings_ccf", DoubleType(), nullable=True),
        StructField("indoor_potable_water_reduction_gallons", DoubleType(), nullable=True),
        StructField(
            "irrigation_potable_water_reduction_gallons_month_of_july",
            DoubleType(),
            nullable=True,
        ),
        StructField("process_portable_water_reduction_1000_gallons_", DoubleType(), nullable=True),
        StructField("construction_waste_diverted_from_landfill_tons", DoubleType(), nullable=True),
        StructField(
            "number_of_aegb_rated_residential_units_outside_ae_service",
            DoubleType(),
            nullable=True,
        ),
        StructField(
            "number_of_aegb_rated_units_in_s_m_a_r_t_developments_outside_ae_service",
            DoubleType(),
            nullable=True,
        ),
        StructField("projects_sq_ft_outside_ae_service", DoubleType(), nullable=True),
        # Leading-underscore field name is a legitimate Socrata-generated key
        # (display label starts with '#').
        StructField("_of_rated_projects_outside_of_ae_service_area", DoubleType(), nullable=True),
        # Floating (no-timezone) calendar dates.
        StructField("start_date", TimestampType(), nullable=True),
        StructField("end_date", TimestampType(), nullable=True),
    ]
)

# Snapshot ingestion: no per-row updated-at field, small dataset re-read in
# full on every sync (captures in-place publisher corrections and deletions).
GREEN_BUILDING_METADATA = {
    "primary_keys": PRIMARY_KEYS,
    "cursor_field": None,
    "ingestion_type": "snapshot",
}
