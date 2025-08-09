#!/usr/bin/env python3

import os
import threading
from typing import Optional, Dict

from skyzone import SkyzoneVTX


class VtxService:
    """Thread-safe, lazy-initialized wrapper for SkyzoneVTX."""

    def __init__(self,
                 clk_pin: Optional[int] = None,
                 mosi_pin: Optional[int] = None,
                 cs_pin: Optional[int] = None):
        self._lock = threading.Lock()
        self._vtx: Optional[SkyzoneVTX] = None
        self._last_error: Optional[str] = None

        # Persisted selected params
        self._band: str = 'A'
        self._channel: int = 1

        # Pin configuration (default to env or None to use SkyzoneVTX defaults)
        self._clk_pin = self._env_int('VTX_CLK_PIN', clk_pin)
        self._mosi_pin = self._env_int('VTX_MOSI_PIN', mosi_pin)
        self._cs_pin = self._env_int('VTX_CS_PIN', cs_pin)

    def _env_int(self, key: str, fallback: Optional[int]) -> Optional[int]:
        try:
            return int(os.environ[key]) if key in os.environ else fallback
        except Exception:
            return fallback

    def _ensure_initialized(self) -> None:
        if self._vtx is not None:
            return
        try:
            # Use provided pins if set, else rely on SkyzoneVTX defaults (27/17/22 as per project)
            if self._clk_pin is not None and self._mosi_pin is not None and self._cs_pin is not None:
                self._vtx = SkyzoneVTX(clk_pin=self._clk_pin, mosi_pin=self._mosi_pin, cs_pin=self._cs_pin)
            else:
                self._vtx = SkyzoneVTX()
            self._last_error = None
        except Exception as e:
            self._vtx = None
            self._last_error = str(e)
            raise

    def set_band_channel(self, band: str, channel: int) -> None:
        band = str(band).upper()
        if band not in ['A', 'B', 'E', 'F', 'R', 'L']:
            raise ValueError('Invalid band')
        if channel < 1 or channel > 8:
            raise ValueError('Invalid channel')

        with self._lock:
            self._ensure_initialized()
            self._vtx.set_channel(band, channel)
            self._band = band
            self._channel = channel

    def get_status(self) -> Dict:
        with self._lock:
            status = {
                'initialized': self._vtx is not None,
                'error': self._last_error,
                'band': self._band,
                'channel': self._channel,
                'frequency_mhz': self._get_frequency_mhz(self._band, self._channel)
            }
            return status

    def _get_frequency_mhz(self, band: str, channel: int) -> int:
        table = {
            'A': [5865, 5845, 5825, 5805, 5785, 5765, 5745, 5725],
            'B': [5733, 5752, 5771, 5790, 5809, 5828, 5847, 5866],
            'E': [5705, 5685, 5665, 5645, 5885, 5905, 5925, 5945],
            'F': [5740, 5760, 5780, 5800, 5820, 5840, 5860, 5880],
            'R': [5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917],
            'L': [5362, 5399, 5436, 5473, 5510, 5547, 5584, 5621]
        }
        try:
            return table[band][channel - 1]
        except Exception:
            return 0


