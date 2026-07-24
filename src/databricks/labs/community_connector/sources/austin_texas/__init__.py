"""Austin, Texas (Socrata SODA) source connector."""

from databricks.labs.community_connector.sources.austin_texas.austin_texas import (
    AustinTexasLakeflowConnect,
)
from databricks.labs.community_connector.sparkpds import LakeflowSource


class AustinTexasDataSource(LakeflowSource):
    _lakeflow_connect_cls = AustinTexasLakeflowConnect
    # Keep the default "lakeflow_connect" format name for now, matching the
    # other connectors in this repo.
    # _format_name = "austin_texas"


__all__ = [
    "AustinTexasLakeflowConnect",
    "AustinTexasDataSource",
]
