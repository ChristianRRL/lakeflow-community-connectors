"""City of Austin, Texas Open Data Portal (Socrata) source connector."""

from databricks.labs.community_connector.sources.hackathon_austin_texas.hackathon_austin_texas import (
    HackathonAustinTexasLakeflowConnect,
)


from databricks.labs.community_connector.sparkpds import LakeflowSource


class HackathonAustinTexasDataSource(LakeflowSource):
    _lakeflow_connect_cls = HackathonAustinTexasLakeflowConnect
    # Override the Spark format name with the source name once this no
    # longer relies on UC connection-option injection. Kept as the default
    # "lakeflow_connect" for now so existing pipelines keep working.
    # _format_name = "hackathon_austin_texas"


__all__ = [
    "HackathonAustinTexasLakeflowConnect",
    "HackathonAustinTexasDataSource",
]
