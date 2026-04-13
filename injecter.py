import logging
from abc import ABC, abstractmethod
from typing import Any

try:
    import pydivert
    from pydivert import Packet, WinDivert
    PYDIVERT_AVAILABLE = True
except Exception:
    pydivert = None
    Packet = Any
    WinDivert = Any
    PYDIVERT_AVAILABLE = False


class TcpInjector(ABC):
    def __init__(
        self,
        w_filter: str,
        queue_len: int | None = None,
        queue_time_ms: int | None = None,
        queue_size_bytes: int | None = None,
        logger: logging.Logger | None = None,
    ):
        if not PYDIVERT_AVAILABLE:
            raise RuntimeError("pydivert is required for WinDivert-based injection mode.")

        self.logger = logger or logging.getLogger("sni_forwarder.injector")
        self.w: WinDivert = WinDivert(w_filter)
        self._set_windivert_param("QUEUE_LEN", queue_len)
        self._set_windivert_param("QUEUE_TIME", queue_time_ms)
        self._set_windivert_param("QUEUE_SIZE", queue_size_bytes)

    def _set_windivert_param(self, param_name: str, value: int | None):
        if value is None or not hasattr(self.w, "set_param") or pydivert is None:
            return
        param_enum = getattr(pydivert, "Param", None)
        if param_enum is None:
            return
        param = getattr(param_enum, param_name, None)
        if param is None:
            return
        try:
            self.w.set_param(param, int(value))
        except Exception:
            self.logger.debug("Failed to set WinDivert param %s=%s", param_name, value, exc_info=True)

    @abstractmethod
    def inject(self, packet: Packet):
        raise NotImplementedError

    def run(self):
        try:
            with self.w:
                self.logger.info("WinDivert started.")
                while True:
                    packet = self.w.recv(65575)
                    self.inject(packet)
        except PermissionError:
            self.logger.error("WinDivert open failed. Run as Administrator on Windows.")
        except Exception:
            self.logger.exception("WinDivert stopped unexpectedly.")
