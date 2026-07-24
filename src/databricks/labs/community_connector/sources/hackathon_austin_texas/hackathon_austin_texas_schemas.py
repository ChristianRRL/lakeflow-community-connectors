"""Schemas, metadata, and constants for the City of Austin (Socrata) connector.

The City of Austin Open Data Portal (``data.austintexas.gov``) is built on the
Socrata Open Data API (SODA).  Every dataset is a REST/JSON resource at
``/resource/{4x4}.json`` and exposes three Socrata *system fields* — ``:id``,
``:created_at``, ``:updated_at`` — which the connector renames to
``system_id`` / ``system_created_at`` / ``system_updated_at`` (Spark column
names cannot contain a leading colon).  ``system_updated_at`` is the universal
CDC cursor for every table.

Socrata quirks reflected here:

* **Numbers arrive as JSON strings** (e.g. ``"1477"``).  Numeric columns are
  declared with their true Spark type; the reader coerces the string form to
  the declared type (see ``COERCION_MAP``).
* **Sparse columns**: a key is omitted entirely for a row when the value is
  blank, so absent fields map to ``NULL`` (the framework handles this).
* **URL fields** appear as a nested ``{"url": "..."}`` struct — modelled as a
  single-field ``StructType`` rather than flattened.
* **Geometry** (``the_geom``, a GeoJSON MultiPolygon) is kept as a JSON string
  (``the_geom_json``) to avoid a fragile nested struct layout.
"""

from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# ---------------------------------------------------------------------------
# HTTP / retry / pagination constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://data.austintexas.gov"
DEFAULT_TIMEOUT = 30  # seconds

RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0  # seconds; doubled after each retry

# Socrata caps a single page at 50,000 rows; 1,000 is a friendly default.
DEFAULT_PAGE_SIZE = 1000
MAX_PAGE_SIZE = 50000

# Partitioning defaults.
DEFAULT_WINDOW_DAYS = 1
DEFAULT_LOOKBACK_MINUTES = 0

# Sentinels for the incremental time cursor (``:updated_at``).
EPOCH_ISO = "1970-01-01T00:00:00.000Z"
# Any start cursor at or before this is treated as a first (full) run and
# collapsed into a single open-ended partition instead of ~20k daily windows.
FIRST_RUN_SENTINEL_THRESHOLD = "2000-01-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Table -> Socrata dataset (4x4) mapping
# ---------------------------------------------------------------------------

DATASET_IDS: dict[str, str] = {
    "transportation_and_mobility": "28ys-ieqv",
    "green_building_ratings_aggregate": "dpvb-c5fy",
    "solar_program_current_incentive_levels_and_available_capacity": "vxq2-zjmn",
    "green_building_energy_code_compliance": "i7vh-fpaj",
    "green_building_developer_agreements": "63mb-dbmj",
    "coa_energy_codes_timeline": "xn7p-rafv",
    "discount_monthly_new_enrollment_by_zip": "guem-bnpv",
}

TABLES: list[str] = list(DATASET_IDS.keys())

# Renamed Socrata system field names, shared by every table.
SYSTEM_ID = "system_id"
SYSTEM_CREATED_AT = "system_created_at"
SYSTEM_UPDATED_AT = "system_updated_at"
CURSOR_FIELD = SYSTEM_UPDATED_AT

# Wire -> Spark name mapping for the three Socrata system fields.
SYSTEM_FIELD_RENAMES = {
    ":id": SYSTEM_ID,
    ":created_at": SYSTEM_CREATED_AT,
    ":updated_at": SYSTEM_UPDATED_AT,
}

# URL fields that arrive as a ``{"url": "..."}`` struct, per table.
URL_STRUCT_FIELDS: dict[str, list[str]] = {
    "transportation_and_mobility": ["dataset_url"],
    "green_building_developer_agreements": ["ordinance_"],
}


def _url_struct() -> StructType:
    return StructType([StructField("url", StringType(), True)])


def _system_fields() -> list[StructField]:
    """The three Socrata system columns prepended to every table schema."""
    return [
        StructField(SYSTEM_ID, StringType(), True),
        StructField(SYSTEM_CREATED_AT, TimestampType(), True),
        StructField(SYSTEM_UPDATED_AT, TimestampType(), True),
    ]


# ---------------------------------------------------------------------------
# Per-table schemas
# ---------------------------------------------------------------------------

_TRANSPORTATION_AND_MOBILITY = StructType(
    _system_fields()
    + [
        StructField("id", StringType(), True),
        StructField("name", StringType(), True),
        StructField("description", StringType(), True),
        StructField("dataset_url", _url_struct(), True),
        StructField("attribution", StringType(), True),
        StructField("type", StringType(), True),
        StructField("update_frequency", StringType(), True),
        StructField("department_name", StringType(), True),
        StructField("program_name", StringType(), True),
        StructField("spatial_information", StringType(), True),
        StructField("strategic_area", StringType(), True),
        StructField("updatedat", TimestampType(), True),
        StructField("createdat", TimestampType(), True),
        StructField("metadata_updated_at", TimestampType(), True),
        StructField("data_updated_at", TimestampType(), True),
        StructField("publication_date", TimestampType(), True),
        StructField("download_count", LongType(), True),
        StructField("page_views_last_week", LongType(), True),
        StructField("page_views_last_month", LongType(), True),
        StructField("page_views_total", LongType(), True),
        StructField("row_count", LongType(), True),
        StructField("cover_image_url", StringType(), True),
        StructField("automation_method", StringType(), True),
        StructField("automation_method_other", StringType(), True),
        StructField("owner_display_name", StringType(), True),
        StructField("tags", StringType(), True),
        StructField("is_public", BooleanType(), True),
    ]
)

_GREEN_BUILDING_RATINGS_AGGREGATE = StructType(
    _system_fields()
    + [
        StructField("class", StringType(), True),
        StructField("fiscal_year", StringType(), True),
        StructField("number_of_projects_aegb_rated", LongType(), True),
        StructField("number_of_projects_leed_reported", LongType(), True),
        StructField("total_square_footage_aegb_rated_projects", DoubleType(), True),
        StructField("number_of_residential_units_aegb_rated", LongType(), True),
        StructField("number_of_smart_housing_units_aegb_rated", LongType(), True),
        StructField("estimated_energy_savings_mbtu", DoubleType(), True),
        StructField("estimated_demand_savings_kw", DoubleType(), True),
        StructField("estimated_electric_energy_savings_kwh", DoubleType(), True),
        # Typed as text in the source despite looking numeric — kept as string.
        StructField("pv_generation_mwh_", StringType(), True),
        StructField("gas_savings_ccf", DoubleType(), True),
        StructField("indoor_potable_water_reduction_gallons", DoubleType(), True),
        StructField(
            "irrigation_potable_water_reduction_gallons_month_of_july",
            DoubleType(),
            True,
        ),
        StructField("process_portable_water_reduction_1000_gallons_", DoubleType(), True),
        StructField(
            "construction_waste_diverted_from_landfill_tons", DoubleType(), True
        ),
        StructField(
            "number_of_aegb_rated_residential_units_outside_ae_service",
            LongType(),
            True,
        ),
        StructField(
            "number_of_aegb_rated_units_in_s_m_a_r_t_developments_outside_ae_service",
            LongType(),
            True,
        ),
        StructField("projects_sq_ft_outside_ae_service", DoubleType(), True),
        StructField("_of_rated_projects_outside_of_ae_service_area", LongType(), True),
        StructField("start_date", TimestampType(), True),
        StructField("end_date", TimestampType(), True),
    ]
)

_SOLAR_PROGRAM = StructType(
    _system_fields()
    + [
        StructField("program", StringType(), True),
        StructField("capacity_requested_kw_ac", DoubleType(), True),
        StructField("capacity_reserved_kw_ac", DoubleType(), True),
        StructField("capacity_available_kw_ac", DoubleType(), True),
        StructField("date_last_updated", TimestampType(), True),
    ]
)

_GREEN_BUILDING_ENERGY_CODE_COMPLIANCE = StructType(
    _system_fields()
    + [
        StructField("fiscal_year", StringType(), True),
        StructField("number_of_residential_building_permits", LongType(), True),
        StructField("residential_energy_code_savings_kw", DoubleType(), True),
        StructField("residential_energy_code_savings_mwh", DoubleType(), True),
        StructField("number_of_multifamily_unit_permits", LongType(), True),
        StructField("multifamily_energy_code_savings_kw", DoubleType(), True),
        StructField("multifamily_energy_code_savings_mwh", DoubleType(), True),
        StructField("square_footage_of_commercial_building_permits", DoubleType(), True),
        StructField("commercial_energy_code_savings_kw", DoubleType(), True),
        StructField("commercial_energy_code_savings_mwh", DoubleType(), True),
        StructField("start_date", TimestampType(), True),
        StructField("end_date", TimestampType(), True),
        StructField("total_energy_code_saving", DoubleType(), True),
        StructField("total_energy_code_savings_mwh_", DoubleType(), True),
    ]
)

_GREEN_BUILDING_DEVELOPER_AGREEMENTS = StructType(
    _system_fields()
    + [
        # GeoJSON MultiPolygon kept as a JSON string for schema stability.
        StructField("the_geom_json", StringType(), True),
        StructField("gis_id", LongType(), True),
        StructField("name", StringType(), True),
        StructField("ordinance_", _url_struct(), True),
        StructField("created_da", TimestampType(), True),
        StructField("shape_area", DoubleType(), True),
        StructField("shape_len", DoubleType(), True),
    ]
)

_COA_ENERGY_CODES_TIMELINE = StructType(
    _system_fields()
    + [
        StructField("effective_date", TimestampType(), True),
        StructField("city_of_austin_energy_code", LongType(), True),
        StructField("residential_energy_code", StringType(), True),
        StructField("commercial_energy_code", StringType(), True),
        StructField("residential_ordinance", StringType(), True),
        StructField("commercial_ordinance", StringType(), True),
        StructField("energy_code_name", StringType(), True),
        StructField("line", LongType(), True),
    ]
)

_DISCOUNT_MONTHLY_NEW_ENROLLMENT_BY_ZIP = StructType(
    _system_fields()
    + [
        StructField("zip_code", StringType(), True),
        StructField("oct_23", LongType(), True),
        StructField("nov_23", LongType(), True),
        StructField("dec_23", LongType(), True),
        StructField("jan_24", LongType(), True),
        StructField("feb_24", LongType(), True),
        StructField("mar_24", LongType(), True),
        StructField("apr_24", LongType(), True),
        StructField("may_24", LongType(), True),
        StructField("jun_24", LongType(), True),
        StructField("jul_24", LongType(), True),
        StructField("aug_24", LongType(), True),
        StructField("sep_24", LongType(), True),
    ]
)


TABLE_SCHEMAS: dict[str, StructType] = {
    "transportation_and_mobility": _TRANSPORTATION_AND_MOBILITY,
    "green_building_ratings_aggregate": _GREEN_BUILDING_RATINGS_AGGREGATE,
    "solar_program_current_incentive_levels_and_available_capacity": _SOLAR_PROGRAM,
    "green_building_energy_code_compliance": _GREEN_BUILDING_ENERGY_CODE_COMPLIANCE,
    "green_building_developer_agreements": _GREEN_BUILDING_DEVELOPER_AGREEMENTS,
    "coa_energy_codes_timeline": _COA_ENERGY_CODES_TIMELINE,
    "discount_monthly_new_enrollment_by_zip": _DISCOUNT_MONTHLY_NEW_ENROLLMENT_BY_ZIP,
}


# ---------------------------------------------------------------------------
# Per-table metadata
# ---------------------------------------------------------------------------
#
# All tables are ``cdc`` keyed on the Socrata ``:updated_at`` system field
# (renamed ``system_updated_at``).  Socrata exposes no delete feed, so
# ``cdc_with_deletes`` is not used (hard-delete detection would require a
# periodic full-snapshot reconciliation, out of scope here).  Primary keys use
# the documented natural key where one exists, falling back to ``system_id``.
TABLE_METADATA: dict[str, dict] = {
    "transportation_and_mobility": {
        "primary_keys": ["id"],
        "cursor_field": CURSOR_FIELD,
        "ingestion_type": "cdc",
    },
    "green_building_ratings_aggregate": {
        # Natural key is composite (class, fiscal_year); use the stable
        # Socrata surrogate ``system_id`` as a single-column PK.
        "primary_keys": [SYSTEM_ID],
        "cursor_field": CURSOR_FIELD,
        "ingestion_type": "cdc",
    },
    "solar_program_current_incentive_levels_and_available_capacity": {
        "primary_keys": ["program"],
        "cursor_field": CURSOR_FIELD,
        "ingestion_type": "cdc",
    },
    "green_building_energy_code_compliance": {
        "primary_keys": ["fiscal_year"],
        "cursor_field": CURSOR_FIELD,
        "ingestion_type": "cdc",
    },
    "green_building_developer_agreements": {
        "primary_keys": ["gis_id"],
        "cursor_field": CURSOR_FIELD,
        "ingestion_type": "cdc",
    },
    "coa_energy_codes_timeline": {
        # No confirmed unique natural key; use the Socrata surrogate.
        "primary_keys": [SYSTEM_ID],
        "cursor_field": CURSOR_FIELD,
        "ingestion_type": "cdc",
    },
    "discount_monthly_new_enrollment_by_zip": {
        "primary_keys": ["zip_code"],
        "cursor_field": CURSOR_FIELD,
        "ingestion_type": "cdc",
    },
}


# ---------------------------------------------------------------------------
# Numeric coercion maps (Socrata returns numbers as JSON strings)
# ---------------------------------------------------------------------------


def _build_coercion_map() -> dict[str, dict[str, str]]:
    """Map each table's LongType/DoubleType leaf columns to a coercion kind."""
    out: dict[str, dict[str, str]] = {}
    for table, schema in TABLE_SCHEMAS.items():
        kinds: dict[str, str] = {}
        for f in schema.fields:
            if isinstance(f.dataType, LongType):
                kinds[f.name] = "long"
            elif isinstance(f.dataType, DoubleType):
                kinds[f.name] = "double"
        out[table] = kinds
    return out


COERCION_MAP: dict[str, dict[str, str]] = _build_coercion_map()
