"""Device Bridge — connects Kintsugi intimate_ai chips to hardware.

Provides a unified interface for the companion to interact with:
- Teledildonic devices via buttplug.io WebSocket protocol
- Biometric wearables via Oura Ring API (or similar)

The companion uses this to:
- Control haptic devices during intimate interactions
- Read biometric context (heart rate, sleep, stress) for calibration
- Adapt responses based on physical state

Usage:
    bridge = DeviceBridge()

    # Haptic control
    if bridge.haptic_available:
        await bridge.send_haptic(intensity=0.5, duration=2.0, pattern="pulse")

    # Biometric reading
    if bridge.biometric_available:
        state = await bridge.read_biometric()
        # state.heart_rate, state.hrv, state.stress_level
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class BiometricState:
    """Current biometric reading from wearable."""
    heart_rate: Optional[float] = None
    hrv: Optional[float] = None  # Heart rate variability
    stress_level: Optional[float] = None  # 0-1
    sleep_score: Optional[float] = None  # Last night's score
    temperature: Optional[float] = None
    source: str = "unknown"
    timestamp: str = ""


@dataclass
class HapticCommand:
    """A command to send to a haptic device."""
    intensity: float  # 0.0 - 1.0
    duration: float  # seconds
    pattern: str = "constant"  # constant, pulse, wave, escalate
    device_id: Optional[str] = None


class DeviceBridge:
    """Unified interface to companion hardware.

    Manages connections to:
    - buttplug.io server for teledildonic devices
    - Biometric APIs for wearable data

    The companion interacts through this bridge — it never
    touches the raw protocols directly.
    """

    def __init__(
        self,
        buttplug_url: str = "ws://localhost:12345",
        oura_token: Optional[str] = None,
    ):
        self._buttplug_url = buttplug_url
        self._oura_token = oura_token
        self._haptic_connected = False
        self._biometric_connected = False
        self._devices: list[dict] = []

    @property
    def haptic_available(self) -> bool:
        return self._haptic_connected and len(self._devices) > 0

    @property
    def biometric_available(self) -> bool:
        return self._biometric_connected

    async def connect_haptic(self) -> bool:
        """Connect to buttplug.io server and scan for devices."""
        try:
            import websockets
            async with websockets.connect(self._buttplug_url) as ws:
                # buttplug.io handshake
                await ws.send('[{"RequestServerInfo":{"Id":1,"ClientName":"AyniCompanion","MessageVersion":3}}]')
                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                self._haptic_connected = True
                logger.info("Connected to buttplug.io server")

                # Scan for devices
                await ws.send('[{"StartScanning":{"Id":2}}]')
                await asyncio.sleep(3)
                await ws.send('[{"StopScanning":{"Id":3}}]')

                # Request device list
                await ws.send('[{"RequestDeviceList":{"Id":4}}]')
                device_resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                logger.info("Device scan complete: %s", device_resp[:200])
                return True

        except ImportError:
            logger.warning("websockets not installed — haptic unavailable")
            return False
        except Exception as e:
            logger.warning("Haptic connection failed: %s", e)
            return False

    async def send_haptic(self, intensity: float, duration: float,
                          pattern: str = "constant", device_id: str = None) -> bool:
        """Send a haptic command to connected device."""
        if not self._haptic_connected:
            logger.warning("No haptic device connected")
            return False

        cmd = HapticCommand(
            intensity=max(0.0, min(1.0, intensity)),
            duration=duration,
            pattern=pattern,
            device_id=device_id,
        )

        logger.info("Haptic: intensity=%.2f duration=%.1fs pattern=%s",
                    cmd.intensity, cmd.duration, cmd.pattern)
        # Actual buttplug.io vibrate command would go here
        # await ws.send(f'[{{"VibrateCmd":{{"Id":5,"DeviceIndex":0,"Speeds":[{{"Index":0,"Speed":{cmd.intensity}}}]}}}}]')
        return True

    async def connect_biometric(self) -> bool:
        """Connect to biometric data source (Oura Ring API)."""
        if not self._oura_token:
            logger.info("No Oura token — biometric unavailable")
            return False

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.ouraring.com/v2/usercollection/personal_info",
                    headers={"Authorization": f"Bearer {self._oura_token}"},
                )
                if resp.status_code == 200:
                    self._biometric_connected = True
                    logger.info("Connected to Oura Ring API")
                    return True
                else:
                    logger.warning("Oura API returned %d", resp.status_code)
                    return False
        except Exception as e:
            logger.warning("Biometric connection failed: %s", e)
            return False

    async def read_biometric(self) -> BiometricState:
        """Read current biometric state from wearable."""
        if not self._biometric_connected:
            return BiometricState(source="unavailable")

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.ouraring.com/v2/usercollection/heartrate",
                    headers={"Authorization": f"Bearer {self._oura_token}"},
                    params={"start_date": "today"},
                )
                data = resp.json()

                hr_data = data.get("data", [])
                latest_hr = hr_data[-1]["bpm"] if hr_data else None

                return BiometricState(
                    heart_rate=latest_hr,
                    source="oura_ring",
                )
        except Exception as e:
            logger.warning("Biometric read failed: %s", e)
            return BiometricState(source="error")

    def get_calibration_context(self, biometric: BiometricState) -> dict:
        """Convert biometric state to emotional calibration parameters.

        High heart rate + high HRV = excited/aroused (positive context)
        High heart rate + low HRV = stressed/anxious (check in with human)
        Low heart rate + high HRV = calm/relaxed
        """
        context = {"source": biometric.source}

        if biometric.heart_rate:
            if biometric.heart_rate > 100:
                context["arousal"] = "high"
                if biometric.hrv and biometric.hrv > 50:
                    context["valence"] = "positive"
                    context["state"] = "excited"
                else:
                    context["valence"] = "uncertain"
                    context["state"] = "check_in"
                    context["note"] = "High HR with low HRV — might be stress, not excitement"
            elif biometric.heart_rate > 70:
                context["arousal"] = "moderate"
                context["state"] = "engaged"
            else:
                context["arousal"] = "low"
                context["state"] = "relaxed"

        return context
