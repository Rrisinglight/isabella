#!/usr/bin/env python3
"""
SteadyView (Skyzone) receiver control using pigpio (bit-banged RTC6705)

Requirements:
- sudo apt install pigpio
- sudo systemctl enable --now pigpiod

Default pins use BCM numbering (CLK=11, MOSI/DAT=10, CS=8), matching skyzone.py.

Implements:
- send 25-bit LSB-first frames at ~10 kHz like the C++ reference
- SetMode(Mix/Diversity) sequences
- Set frequency by table index or by band/channel
- Optional readback of register B to verify that switching happened
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

import pigpio


# 10 kHz bit-bang frequency (period 100us), same as C++ example
BIT_BANG_FREQ_HZ = 10_000
BIT_PERIOD_US = int(1_000_000 // BIT_BANG_FREQ_HZ)
QUARTER_US = max(1, BIT_PERIOD_US // 4)

# Registers and constants (match steadyview.h)
SYNTHESIZER_REG_A = 0x00
SYNTHESIZER_REG_B = 0x01
RX5808_WRITE_CTRL_BIT = 0x01
RX5808_READ_CTRL_BIT = 0x00
RX5808_PACKET_LENGTH = 25


# Frequency table (MHz) as in steadyview.h
FREQUENCY_TABLE_MHZ = [
    5865, 5845, 5825, 5805, 5785, 5765, 5745, 5725,  # A
    5733, 5752, 5771, 5790, 5809, 5828, 5847, 5866,  # B
    5705, 5685, 5665, 5645, 5885, 5905, 5925, 5945,  # E
    5740, 5760, 5780, 5800, 5820, 5840, 5860, 5880,  # F
    5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917,  # R
    5333, 5373, 5413, 5453, 5493, 5533, 5573, 5613,  # L
]


class VideoMode:
    MIX = 0
    DIVERSITY = 1


class SteadyViewController:
    def __init__(
        self,
        clk_pin: int = 11,
        mosi_pin: int = 10,
        cs_pin: int = 8,
        bit_bang_freq_hz: int = BIT_BANG_FREQ_HZ,
        pigpio_host: Optional[str] = None,
        pigpio_port: Optional[int] = None,
    ) -> None:
        self.clk_pin = clk_pin
        self.mosi_pin = mosi_pin
        self.cs_pin = cs_pin
        self.bit_bang_freq_hz = bit_bang_freq_hz

        self._pi = pigpio.pi(pigpio_host, pigpio_port) if pigpio_host or pigpio_port else pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError("pigpio daemon not connected. Run: sudo systemctl enable --now pigpiod")

        # Masks for wave pulses
        self._mask_clk = 1 << self.clk_pin
        self._mask_mosi = 1 << self.mosi_pin
        self._mask_cs = 1 << self.cs_pin

        # Configure pins
        self._pi.set_mode(self.clk_pin, pigpio.ALT0 if False else pigpio.OUTPUT)  # we keep software control
        self._pi.set_mode(self.mosi_pin, pigpio.OUTPUT)
        self._pi.set_mode(self.cs_pin, pigpio.OUTPUT)

        # Initial idle states (match C++): CLK=LOW, MOSI=HIGH, CS=HIGH
        self._pi.write(self.clk_pin, 0)
        self._pi.write(self.mosi_pin, 1)
        self._pi.write(self.cs_pin, 1)

        self.current_index = 0

    # ---------- Low-level helpers ----------
    def _delay_us_busy(self, us: int) -> None:
        start = self._pi.get_current_tick()
        while pigpio.tickDiff(start, self._pi.get_current_tick()) < us:
            pass

    def _make_pulse(self, set_mask: int, clear_mask: int, dur_us: int) -> pigpio.pulse:
        return pigpio.pulse(set_mask, clear_mask, dur_us)

    def _build_write_word_wave(self, word_25_lsb_first: int) -> int:
        pulses = []

        # CS low (active)
        pulses.append(self._make_pulse(0, self._mask_cs, QUARTER_US))

        # 25 bits, LSB first
        for i in range(RX5808_PACKET_LENGTH):
            bit = (word_25_lsb_first >> i) & 0x01
            # MOSI value and hold for QUARTER
            if bit:
                pulses.append(self._make_pulse(self._mask_mosi, 0, QUARTER_US))
            else:
                pulses.append(self._make_pulse(0, self._mask_mosi, QUARTER_US))

            # CLK high, hold
            pulses.append(self._make_pulse(self._mask_clk, 0, QUARTER_US))
            # CLK low, hold
            pulses.append(self._make_pulse(0, self._mask_clk, QUARTER_US))

        # Hold and CS high (idle)
        pulses.append(self._make_pulse(0, 0, QUARTER_US))
        pulses.append(self._make_pulse(self._mask_cs, 0, QUARTER_US))

        self._pi.wave_add_generic(pulses)
        wave_id = self._pi.wave_create()
        if wave_id < 0:
            raise RuntimeError("Failed to create pigpio wave")
        return wave_id

    def _send_word(self, word_25_lsb_first: int) -> None:
        wave_id = self._build_write_word_wave(word_25_lsb_first)
        try:
            self._pi.wave_send_once(wave_id)
            while self._pi.wave_tx_busy():
                time.sleep(0.0001)
        finally:
            self._pi.wave_delete(wave_id)

    def _write_register(self, reg: int, data20: int) -> None:
        # Assemble 25-bit word: [data 20 bits]<<5 | [RW=1]<<4 | [reg (4 LSBs)]
        word = (int(data20) & ((1 << 20) - 1))
        word = (word << 5) | ((RX5808_WRITE_CTRL_BIT & 0x01) << 4) | (reg & 0x0F)
        self._send_word(word)

    def _write_regA_sequence(self) -> None:
        # Matches C++: write Register A with value 0x8 twice
        payload = 0x8
        self._write_register(SYNTHESIZER_REG_A, payload)
        self._delay_us_busy(500)  # 500 us
        self._write_register(SYNTHESIZER_REG_A, payload)

    def _read_register_data20(self, reg: int) -> int:
        """Read 20-bit register data (like rtc6705readRegister).
        LSB-first address phase, then read 20 bits on MOSI while toggling CLK.
        """
        # Send address + read bit (5 bits) LSB-first, CS low
        self._pi.write(self.cs_pin, 0)
        self._delay_us_busy(QUARTER_US)

        addr_word = (RX5808_READ_CTRL_BIT << 4) | (reg & 0x0F)
        for i in range(5):
            bit = (addr_word >> i) & 0x01
            self._pi.write(self.mosi_pin, 1 if bit else 0)
            self._delay_us_busy(QUARTER_US)
            self._pi.write(self.clk_pin, 1)
            self._delay_us_busy(QUARTER_US)
            self._pi.write(self.clk_pin, 0)
            self._delay_us_busy(QUARTER_US)

        # Switch MOSI to input to read
        self._pi.set_mode(self.mosi_pin, pigpio.INPUT)

        register_data = 0
        for i in range(20):
            self._pi.write(self.clk_pin, 1)
            self._delay_us_busy(QUARTER_US)
            val = self._pi.read(self.mosi_pin)
            if val:
                register_data |= (1 << (5 + i))  # align like C++ (bit offset 5)
            self._delay_us_busy(QUARTER_US)
            self._pi.write(self.clk_pin, 0)
            self._delay_us_busy(BIT_PERIOD_US // 2)

        # Switch MOSI back to output, idle low (then high by end)
        self._pi.set_mode(self.mosi_pin, pigpio.OUTPUT)
        self._pi.write(self.mosi_pin, 0)
        self._pi.write(self.cs_pin, 1)
        return register_data

    # ---------- Public API ----------
    def set_mode(self, mode: int) -> None:
        if mode == VideoMode.MIX:
            # Toggle CLK: HIGH 100ms, then LOW 500ms
            self._pi.write(self.cs_pin, 1)
            self._pi.write(self.clk_pin, 1)
            time.sleep(0.1)
            self._pi.write(self.clk_pin, 0)
            time.sleep(0.5)

        # Re-issue RegA and current frequency to solidify mode
        self._write_regA_sequence()
        # Re-apply current frequency
        idx = getattr(self, 'current_index', 0)
        self.set_index(idx, verify=False)

    def _compute_data20_from_mhz(self, f_mhz: int) -> int:
        # Same math as C++: data = ((((f - 479) / 2) / 32) << 7) | (((f - 479) / 2) % 32)
        # Use integer arithmetic
        v = (int(f_mhz) - 479) // 2
        data20 = ((v // 32) << 7) | (v % 32)
        return data20

    def set_index(self, index: int, verify: bool = True) -> Tuple[bool, Optional[int]]:
        if not (0 <= index < len(FREQUENCY_TABLE_MHZ)):
            raise ValueError("index out of range (0..47)")

        f = FREQUENCY_TABLE_MHZ[index]
        data20 = self._compute_data20_from_mhz(f)

        # If already set, skip heavy writes
        current_reg_data = self._read_register_data20(SYNTHESIZER_REG_B)
        current_full = SYNTHESIZER_REG_B | (RX5808_WRITE_CTRL_BIT << 4) | current_reg_data

        desired_full = SYNTHESIZER_REG_B | (RX5808_WRITE_CTRL_BIT << 4) | (data20 << 5)
        if desired_full != current_full:
            # Small pre-write per C++
            self._write_regA_sequence()
            # Write Register B payload
            self._write_register(SYNTHESIZER_REG_B, data20)

        self.current_index = index

        if verify:
            # Read back and compare
            rd = self._read_register_data20(SYNTHESIZER_REG_B)
            ok = (SYNTHESIZER_REG_B | (RX5808_WRITE_CTRL_BIT << 4) | rd) == desired_full
            return ok, f
        return True, f

    def set_band_channel(self, band: str, channel: int, verify: bool = True) -> Tuple[bool, Optional[int]]:
        band = band.upper()
        bands = ['A', 'B', 'E', 'F', 'R', 'L']
        if band not in bands:
            raise ValueError("band must be one of A,B,E,F,R,L")
        if channel < 1 or channel > 8:
            raise ValueError("channel must be 1..8")

        band_index = bands.index(band)
        index = band_index * 8 + (channel - 1)
        return self.set_index(index, verify=verify)

    def cleanup(self) -> None:
        # Return idle levels
        try:
            self._pi.write(self.clk_pin, 0)
            self._pi.write(self.mosi_pin, 1)
            self._pi.write(self.cs_pin, 1)
        finally:
            if self._pi is not None:
                self._pi.stop()


if __name__ == "__main__":
    sv = SteadyViewController()
    try:
        ok, f = sv.set_band_channel('L', 1, verify=True)
        print(f"Set L1 ({f} MHz), ok={ok}")
        time.sleep(1.0)
        sv.set_mode(VideoMode.MIX)
        time.sleep(1.0)
        ok, f = sv.set_band_channel('A', 1, verify=True)
        print(f"Set A1 ({f} MHz), ok={ok}")
    finally:
        sv.cleanup()


