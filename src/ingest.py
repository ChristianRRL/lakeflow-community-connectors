
# Databricks notebook source

from databricks.labs.community_connector.pipeline import ingest
from databricks.labs.community_connector import register

# COMMAND ----------

# Enable the injection of connection options from Unity Catalog connections into connectors
spark.conf.set("spark.databricks.unityCatalog.connectionDfOptionInjection.enabled", "true")

# COMMAND ----------

source_name = "google_maps_solar"
locations = "lat/lng pairs (semicolon-separated)"

# COMMAND ----------

# =============================================================================
# INGESTION PIPELINE CONFIGURATION
# =============================================================================
#
# pipeline_spec
# ├── connection_name (required): The Unity Catalog connection name
# └── objects[]: List of tables to ingest
#     └── table
#         ├── source_table (required): The table name in the source system
#         ├── destination_catalog (optional): Target catalog (defaults to pipeline's default)
#         ├── destination_schema (optional): Target schema (defaults to pipeline's default)
#         ├── destination_table (optional): Target table name (defaults to source_table)
#         └── table_configuration (optional)
#             ├── scd_type: "SCD_TYPE_1" (default), "SCD_TYPE_2", or "APPEND_ONLY"
#             ├── primary_keys: List of columns to override connector's default keys
#             └── (other options): See source connector's README
# =============================================================================

# Please update the spec below to configure your ingestion pipeline.
#
# All three Solar API tables are lookup-style and require at least one query
# location (see README.md). Replace the example lat/lng pairs below with your
# own before running. `geo_tiff` overrides `primary_keys` because its default
# key (`asset_id`) is regenerated on every run (signed URLs expire ~1 hour
# after they're issued) — see README.md "Special table_configuration options".

pipeline_spec = {
    "connection_name": "google_maps_solar_connection",
    "objects": [
        {
            "table": {
                "source_table": "building_insights",
                "table_configuration": {
                    "locations": locations,
                    "requiredQuality": "HIGH",
                    "additionalInsights": "DETECTED_ARRAYS",
                },
            }
        },
        {
            "table": {
                "source_table": "data_layers",
                "table_configuration": {
                    "locations": locations,
                    "radiusMeters": "100",
                    "view": "FULL_LAYERS",
                    "pixelSizeMeters": "0.5",
                },
            }
        },
        {
            "table": {
                "source_table": "geo_tiff",
                "table_configuration": {
                    "locations": locations,
                    "radiusMeters": "100",
                    "view": "IMAGERY_AND_ANNUAL_FLUX_LAYERS",
                    "layer_types": "dsm,rgb,annual_flux",
                    "max_assets_per_location": "5",
                    "primary_keys": ["query_latitude", "query_longitude", "layer_type", "month_index"],
                },
            }
        },
        # ... more tables/locations to ingest...
    ],
}


# COMMAND ----------

# Dynamically import and register the LakeFlow source
register(spark, source_name)

# COMMAND ----------

# Ingest the tables specified in the pipeline spec
ingest(spark, pipeline_spec)
