# Databricks notebook source
from databricks.labs.community_connector.pipeline import ingest
from databricks.labs.community_connector import register

# Enable the injection of connection options from Unity Catalog connections into connectors
spark.conf.set("spark.databricks.unityCatalog.connectionDfOptionInjection.enabled", "true")

# COMMAND ----------

source_name = "hackathon_austin_texas"

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

pipeline_spec = {
    "connection_name": "hackathon_austin_texas_static_credential",
    "objects": [
        # City of Austin Open Data Portal datasets (data.austintexas.gov)
        {
            "table": {
                "source_table": "transportation_and_mobility",
            }
        },
        {
            "table": {
                "source_table": "green_building_ratings_aggregate",
            }
        },
        {
            "table": {
                "source_table": "solar_program_current_incentive_levels_and_available_capacity",
            }
        },
        {
            "table": {
                "source_table": "green_building_energy_code_compliance",
            }
        },
        {
            "table": {
                "source_table": "green_building_developer_agreements",
            }
        },
        {
            "table": {
                "source_table": "coa_energy_codes_timeline",
            }
        },
        {
            "table": {
                "source_table": "discount_monthly_new_enrollment_by_zip",
            }
        },
    ],
}

# COMMAND ----------

# Dynamically import and register the LakeFlow source
register(spark, source_name)

# Ingest the tables specified in the pipeline spec
ingest(spark, pipeline_spec)
