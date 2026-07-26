"""Static schemas, metadata and constants for the Google Maps Platform Solar API.

The Solar API (``solar.googleapis.com``, REST ``v1``) is proto-derived: its
schemas are fixed and fully documented, and there is no schema-discovery
endpoint.  Everything here is therefore hard-coded from
``google_maps_solar_api_doc.md``.

Nested JSON objects are modelled as ``StructType`` (never flattened, never
``MapType``) so the tabular view keeps the API's shape.  ``LongType`` is
preferred over ``IntegerType`` throughout to avoid overflow.
"""

from pyspark.sql.types import (
    ArrayType,
    BinaryType,
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# ----- connection / HTTP constants ---------------------------------------

DEFAULT_BASE_URL = "https://solar.googleapis.com"
API_VERSION = "v1"

#: Timeout for the two JSON lookup endpoints.
DEFAULT_TIMEOUT = 30
#: GeoTIFF payloads can be a few MB, so they get a longer budget.
GEO_TIFF_TIMEOUT = 120

MAX_RETRIES = 4
INITIAL_BACKOFF = 1.0
#: 429 is the documented response when the shared 600 QPM quota is exceeded.
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# ----- table names --------------------------------------------------------

TABLE_BUILDING_INSIGHTS = "building_insights"
TABLE_DATA_LAYERS = "data_layers"
TABLE_GEO_TIFF = "geo_tiff"

TABLES = [TABLE_BUILDING_INSIGHTS, TABLE_DATA_LAYERS, TABLE_GEO_TIFF]

# ----- endpoint paths -----------------------------------------------------

PATH_BUILDING_INSIGHTS = f"/{API_VERSION}/buildingInsights:findClosest"
PATH_DATA_LAYERS = f"/{API_VERSION}/dataLayers:get"
PATH_GEO_TIFF = f"/{API_VERSION}/geoTiff:get"

# ----- geo_tiff layer mapping --------------------------------------------

#: ``dataLayers:get`` response field -> connector ``layer_type`` value.
#: Ordered so ``geo_tiff`` rows come back in a stable, documented sequence.
GEO_TIFF_SCALAR_LAYERS = {
    "dsmUrl": "dsm",
    "rgbUrl": "rgb",
    "maskUrl": "mask",
    "annualFluxUrl": "annual_flux",
    "monthlyFluxUrl": "monthly_flux",
}

#: The one repeated URL field: 12 entries, Jan..Dec, one GeoTIFF per month.
GEO_TIFF_ARRAY_FIELD = "hourlyShadeUrls"
GEO_TIFF_ARRAY_LAYER = "hourly_shade"

GEO_TIFF_LAYER_TYPES = list(GEO_TIFF_SCALAR_LAYERS.values()) + [GEO_TIFF_ARRAY_LAYER]

# ----- shared google.type.* sub-structs -----------------------------------

#: ``google.type.LatLng``
LAT_LNG = StructType(
    [
        StructField("latitude", DoubleType(), True),
        StructField("longitude", DoubleType(), True),
    ]
)

#: A south-west / north-east pair of ``LatLng``.
LAT_LNG_BOX = StructType(
    [
        StructField("sw", LAT_LNG, True),
        StructField("ne", LAT_LNG, True),
    ]
)

#: ``google.type.Date``.  Deliberately *not* a Spark ``DateType``: the proto
#: allows partial dates (month/day may legally be 0), which would silently
#: fail to coerce.
DATE = StructType(
    [
        StructField("year", LongType(), True),
        StructField("month", LongType(), True),
        StructField("day", LongType(), True),
    ]
)

#: ``google.type.Money``.  ``units`` arrives as a *string-encoded* int64 on
#: the wire; the framework's LongType parser accepts that string form.
MONEY = StructType(
    [
        StructField("currencyCode", StringType(), True),
        StructField("units", LongType(), True),
        StructField("nanos", LongType(), True),
    ]
)

# ----- building_insights nested structs -----------------------------------

SIZE_AND_SUNSHINE_STATS = StructType(
    [
        StructField("areaMeters2", DoubleType(), True),
        StructField("sunshineQuantiles", ArrayType(DoubleType()), True),
        StructField("groundAreaMeters2", DoubleType(), True),
    ]
)

ROOF_SEGMENT_SIZE_AND_SUNSHINE_STATS = StructType(
    [
        StructField("pitchDegrees", DoubleType(), True),
        StructField("azimuthDegrees", DoubleType(), True),
        StructField("stats", SIZE_AND_SUNSHINE_STATS, True),
        StructField("center", LAT_LNG, True),
        StructField("boundingBox", LAT_LNG_BOX, True),
        StructField("planeHeightAtCenterMeters", DoubleType(), True),
    ]
)

SOLAR_PANEL = StructType(
    [
        StructField("center", LAT_LNG, True),
        # SolarPanelOrientation enum, kept as its string constant.
        StructField("orientation", StringType(), True),
        StructField("yearlyEnergyDcKwh", DoubleType(), True),
        StructField("segmentIndex", LongType(), True),
    ]
)

ROOF_SEGMENT_SUMMARY = StructType(
    [
        StructField("pitchDegrees", DoubleType(), True),
        StructField("azimuthDegrees", DoubleType(), True),
        StructField("panelsCount", LongType(), True),
        StructField("yearlyEnergyDcKwh", DoubleType(), True),
        StructField("segmentIndex", LongType(), True),
    ]
)

SOLAR_PANEL_CONFIG = StructType(
    [
        StructField("panelsCount", LongType(), True),
        StructField("yearlyEnergyDcKwh", DoubleType(), True),
        StructField("roofSegmentSummaries", ArrayType(ROOF_SEGMENT_SUMMARY), True),
    ]
)

SAVINGS_OVER_TIME = StructType(
    [
        StructField("savingsYear1", MONEY, True),
        StructField("savingsYear20", MONEY, True),
        StructField("presentValueOfSavingsYear20", MONEY, True),
        StructField("savingsLifetime", MONEY, True),
        StructField("presentValueOfSavingsLifetime", MONEY, True),
        StructField("financiallyViable", BooleanType(), True),
    ]
)

FINANCIAL_DETAILS = StructType(
    [
        StructField("initialAcKwhPerYear", DoubleType(), True),
        StructField("remainingLifetimeUtilityBill", MONEY, True),
        StructField("federalIncentive", MONEY, True),
        StructField("stateIncentive", MONEY, True),
        StructField("utilityIncentive", MONEY, True),
        StructField("lifetimeSrecTotal", MONEY, True),
        StructField("costOfElectricityWithoutSolar", MONEY, True),
        StructField("netMeteringAllowed", BooleanType(), True),
        StructField("solarPercentage", DoubleType(), True),
        StructField("percentageExportedToGrid", DoubleType(), True),
    ]
)

LEASING_SAVINGS = StructType(
    [
        StructField("leasesAllowed", BooleanType(), True),
        StructField("leasesSupported", BooleanType(), True),
        StructField("annualLeasingCost", MONEY, True),
        StructField("savings", SAVINGS_OVER_TIME, True),
    ]
)

CASH_PURCHASE_SAVINGS = StructType(
    [
        StructField("outOfPocketCost", MONEY, True),
        StructField("upfrontCost", MONEY, True),
        StructField("rebateValue", MONEY, True),
        StructField("paybackYears", DoubleType(), True),
        StructField("savings", SAVINGS_OVER_TIME, True),
    ]
)

#: Same shape as ``CashPurchaseSavings`` plus the loan rate.
FINANCED_PURCHASE_SAVINGS = StructType(
    [
        StructField("annualLoanPayment", MONEY, True),
        StructField("rebateValue", MONEY, True),
        StructField("loanInterestRate", DoubleType(), True),
        StructField("savings", SAVINGS_OVER_TIME, True),
    ]
)

FINANCIAL_ANALYSIS = StructType(
    [
        StructField("monthlyBill", MONEY, True),
        StructField("defaultBill", BooleanType(), True),
        StructField("averageKwhPerMonth", DoubleType(), True),
        StructField("panelConfigIndex", LongType(), True),
        StructField("financialDetails", FINANCIAL_DETAILS, True),
        StructField("leasingSavings", LEASING_SAVINGS, True),
        StructField("cashPurchaseSavings", CASH_PURCHASE_SAVINGS, True),
        StructField("financedPurchaseSavings", FINANCED_PURCHASE_SAVINGS, True),
    ]
)

SOLAR_POTENTIAL = StructType(
    [
        StructField("maxArrayPanelsCount", LongType(), True),
        StructField("panelCapacityWatts", DoubleType(), True),
        StructField("panelHeightMeters", DoubleType(), True),
        StructField("panelWidthMeters", DoubleType(), True),
        StructField("panelLifetimeYears", LongType(), True),
        StructField("maxArrayAreaMeters2", DoubleType(), True),
        StructField("maxSunshineHoursPerYear", DoubleType(), True),
        StructField("carbonOffsetFactorKgPerMwh", DoubleType(), True),
        StructField("wholeRoofStats", SIZE_AND_SUNSHINE_STATS, True),
        StructField("buildingStats", SIZE_AND_SUNSHINE_STATS, True),
        StructField(
            "roofSegmentStats",
            ArrayType(ROOF_SEGMENT_SIZE_AND_SUNSHINE_STATS),
            True,
        ),
        StructField("solarPanels", ArrayType(SOLAR_PANEL), True),
        StructField("solarPanelConfigs", ArrayType(SOLAR_PANEL_CONFIG), True),
        StructField("financialAnalyses", ArrayType(FINANCIAL_ANALYSIS), True),
    ]
)

#: Only populated when ``additionalInsights=DETECTED_ARRAYS`` is requested.
DETECTED_ARRAYS = StructType(
    [
        StructField("detectionStatus", StringType(), True),
        StructField("latestCaptureDate", DATE, True),
    ]
)

# ----- table schemas ------------------------------------------------------

BUILDING_INSIGHTS_SCHEMA = StructType(
    [
        StructField("name", StringType(), True),
        StructField("center", LAT_LNG, True),
        StructField("boundingBox", LAT_LNG_BOX, True),
        StructField("imageryDate", DATE, True),
        StructField("imageryProcessedDate", DATE, True),
        StructField("postalCode", StringType(), True),
        StructField("administrativeArea", StringType(), True),
        StructField("statisticalArea", StringType(), True),
        StructField("regionCode", StringType(), True),
        StructField("imageryQuality", StringType(), True),
        StructField("solarPotential", SOLAR_POTENTIAL, True),
        StructField("detectedArrays", DETECTED_ARRAYS, True),
    ]
)

DATA_LAYERS_SCHEMA = StructType(
    [
        StructField("imageryDate", DATE, True),
        StructField("imageryProcessedDate", DATE, True),
        StructField("dsmUrl", StringType(), True),
        StructField("rgbUrl", StringType(), True),
        StructField("maskUrl", StringType(), True),
        StructField("annualFluxUrl", StringType(), True),
        StructField("monthlyFluxUrl", StringType(), True),
        StructField("hourlyShadeUrls", ArrayType(StringType()), True),
        StructField("imageryQuality", StringType(), True),
        # Connector-derived: the request parameters are the only stable
        # identity a dataLayers response has.
        StructField("query_latitude", DoubleType(), True),
        StructField("query_longitude", DoubleType(), True),
        StructField("query_radius_meters", DoubleType(), True),
    ]
)

GEO_TIFF_SCHEMA = StructType(
    [
        StructField("asset_id", StringType(), True),
        StructField("layer_type", StringType(), True),
        StructField("month_index", LongType(), True),
        StructField("content_type", StringType(), True),
        # Raw GeoTIFF bytes.  Stored as BinaryType rather than a base64
        # string to avoid ~33% size bloat and a pointless encode/decode.
        StructField("data", BinaryType(), True),
        StructField("source_url", StringType(), True),
        StructField("query_latitude", DoubleType(), True),
        StructField("query_longitude", DoubleType(), True),
        StructField("fetched_at", TimestampType(), True),
    ]
)

TABLE_SCHEMAS = {
    TABLE_BUILDING_INSIGHTS: BUILDING_INSIGHTS_SCHEMA,
    TABLE_DATA_LAYERS: DATA_LAYERS_SCHEMA,
    TABLE_GEO_TIFF: GEO_TIFF_SCHEMA,
}

# ----- table metadata -----------------------------------------------------

# Every object is a point-in-time lookup: no endpoint accepts an
# ``updatedSince``-style filter and no response exposes a revision or
# modification timestamp, so there is no usable cursor anywhere in this API.
# All three tables are therefore ``snapshot`` with ``cursor_field: None``.
TABLE_METADATA = {
    TABLE_BUILDING_INSIGHTS: {
        "primary_keys": ["name"],
        "cursor_field": None,
        "ingestion_type": "snapshot",
    },
    TABLE_DATA_LAYERS: {
        "primary_keys": [
            "query_latitude",
            "query_longitude",
            "query_radius_meters",
        ],
        "cursor_field": None,
        "ingestion_type": "snapshot",
    },
    TABLE_GEO_TIFF: {
        "primary_keys": ["asset_id"],
        "cursor_field": None,
        "ingestion_type": "snapshot",
    },
}
