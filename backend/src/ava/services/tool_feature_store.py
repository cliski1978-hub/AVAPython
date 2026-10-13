from threading import Lock

from ava.contracts.tool_features import ToolFeatureConfiguration
from ava.repositories.tool_feature_repository import ToolFeatureConflictError, ToolFeatureRepository


class ToolFeatureStore(ToolFeatureRepository):
    def __init__(self) -> None:
        self._configuration: ToolFeatureConfiguration | None = None
        self._lock = Lock()

    def get(self) -> ToolFeatureConfiguration | None:
        with self._lock:
            return self._configuration

    def compare_and_set(self, expected_version: int, configuration: ToolFeatureConfiguration) -> None:
        if configuration.configuration_version != expected_version + 1:
            raise ValueError("configuration version must advance by one")
        with self._lock:
            version = self._configuration.configuration_version if self._configuration else 0
            if version != expected_version:
                raise ToolFeatureConflictError("Feature configuration changed; reload before saving.")
            self._configuration = configuration
