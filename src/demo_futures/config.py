from dataclasses import dataclass, field
from pathlib import Path
import os

DEMO_REST = "https://demo-fapi.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
INTERVALS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


class SafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)
    environment: str = "demo"
    base_url: str = DEMO_REST

    def validate(self):
        if self.environment != "demo" or self.base_url != DEMO_REST:
            raise SafetyError("Only the fixed Binance Demo HTTPS endpoint is permitted")
        if bool(self.api_key) != bool(self.api_secret):
            raise SafetyError("Both Demo credentials must be provided together")
        if any(c in self.api_key for c in "\r\n"):
            raise SafetyError("Invalid API key format")

    @classmethod
    def load(cls, path=Path(".env")):
        # Deliberately small dotenv subset; never execute or interpolate file contents.
        values = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, sep, value = line.partition("=")
                if not sep:
                    raise SafetyError("Invalid .env assignment")
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key.strip()] = value
        def get(key, default=""):
            return os.environ.get(key, values.get(key, default))
        # Reject common accidental production URL overrides rather than ignore them.
        result = cls(get("BINANCE_DEMO_API_KEY"), get("BINANCE_DEMO_API_SECRET"),
                     get("BINANCE_ENV", "demo"), get("BINANCE_BASE_URL", DEMO_REST))
        result.validate()
        return result
