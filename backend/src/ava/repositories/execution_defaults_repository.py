"""AVA-owned persistence port for application execution defaults.

The port is deliberately singular. A deployment has at most one application-wide
defaults record, so it exposes ``get``/``set`` rather than the generic
``create``/``list``/``update``/``delete`` collection shape used by the
configured-record repositories. There is no deletion: clearing a default is
setting a new one, and "no defaults configured" is the absent state.
"""

from abc import ABC, abstractmethod

from ava.configuration.execution_defaults import ApplicationExecutionDefaults


class ExecutionDefaultsRepository(ABC):
    """Store the application's single default execution selection."""

    @abstractmethod
    def get(self) -> ApplicationExecutionDefaults | None:
        """Return the current defaults, or ``None`` when none are configured."""
        raise NotImplementedError

    @abstractmethod
    def set(self, defaults: ApplicationExecutionDefaults) -> ApplicationExecutionDefaults:
        """Replace the current defaults after validating every reference.

        Raises:
            ValueError: If any referenced record is missing, disabled, or if
                the selected model does not belong to the selected provider
                connection.
        """
        raise NotImplementedError
