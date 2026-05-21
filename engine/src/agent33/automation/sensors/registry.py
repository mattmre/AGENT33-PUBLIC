"""Sensor registry -- central catalog for all sensor instances."""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Sensor(Protocol):
    """Protocol that sensors should implement for lifecycle management."""

    def start(self) -> None: ...
    def stop(self) -> None: ...


class SensorRegistry:
    """Central registry for named sensor instances with lifecycle control."""

    def __init__(self) -> None:
        self._sensors: dict[str, Any] = {}

    def register(self, name: str, sensor: Any) -> None:
        """Register a sensor under the given name.

        Parameters
        ----------
        name:
            Unique name for the sensor.
        sensor:
            Sensor instance. Should implement ``start()`` and ``stop()``
            methods for lifecycle management.
        """
        self._sensors[name] = sensor
        logger.info("Registered sensor: %s", name)

    def get(self, name: str) -> Any | None:
        """Return the sensor registered under *name*, or None."""
        return self._sensors.get(name)

    def list_all(self) -> dict[str, Any]:
        """Return all registered sensors as a name-to-instance mapping."""
        return dict(self._sensors)

    def start_all(self) -> None:
        """Call ``start()`` on every registered sensor that supports it."""
        for name, sensor in self._sensors.items():
            if hasattr(sensor, "start"):
                try:
                    sensor.start()
                    logger.info("Started sensor: %s", name)
                except Exception:
                    logger.exception("Failed to start sensor: %s", name)

    def stop_all(self) -> None:
        """Call ``stop()`` on every registered sensor that supports it."""
        for name, sensor in self._sensors.items():
            if hasattr(sensor, "stop"):
                try:
                    sensor.stop()
                    logger.info("Stopped sensor: %s", name)
                except Exception:
                    logger.exception("Failed to stop sensor: %s", name)
