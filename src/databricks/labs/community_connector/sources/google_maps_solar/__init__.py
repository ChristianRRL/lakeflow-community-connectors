"""Google Maps Platform Solar API source connector."""

from databricks.labs.community_connector.sources.google_maps_solar.google_maps_solar import (
    GoogleMapsSolarLakeflowConnect,
)

from databricks.labs.community_connector.sparkpds import LakeflowSource


class GoogleMapsSolarDataSource(LakeflowSource):
    _lakeflow_connect_cls = GoogleMapsSolarLakeflowConnect


__all__ = [
    "GoogleMapsSolarLakeflowConnect",
    "GoogleMapsSolarDataSource",
]
