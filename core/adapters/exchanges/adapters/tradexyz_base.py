"""
TradeXYZ base helpers.

TradeXYZ reuses Hyperliquid's API endpoints, while XYZ assets are exposed
through the `dex="xyz"` namespace and use `xyz:`-prefixed coin identifiers.
"""

from pathlib import Path
from typing import List

import yaml

from .hyperliquid_base import HyperliquidBase


class TradeXYZBase(HyperliquidBase):
    """Base utilities for symbol normalization and config loading."""

    XYZ_DEX = "xyz"
    XYZ_COIN_PREFIX = "xyz:"

    XYZ_ASSET_CLASSES = {
        "us_stocks": [
            "AAPL",
            "AMZN",
            "GOOGL",
            "META",
            "MSFT",
            "NVDA",
            "TSLA",
            "AMD",
            "PLTR",
            "COIN",
            "MSTR",
            "NFLX",
            "CRM",
            "UBER",
            "SQ",
            "SHOP",
            "SNOW",
            "ABNB",
            "RBLX",
            "HOOD",
            "BA",
            "DIS",
            "JPM",
            "V",
            "MA",
            "WMT",
            "KO",
            "PEP",
            "MCD",
            "NKE",
            "PYPL",
            "INTC",
            "QCOM",
            "AVGO",
        ],
        "indices": ["SP500", "XYZ100"],
        "commodities": [
            "GOLD",
            "SILVER",
            "PLATINUM",
            "PALLADIUM",
            "COPPER",
            "WTIOIL",
            "BRENTOIL",
            "NATGAS",
        ],
        "fx": ["EUR/USD", "USD/JPY"],
        "korean_equities": ["SMSN", "SKHX", "HYUNDAI", "EWY"],
    }

    def __init__(self, config=None):
        super().__init__(config)
        self.xyz_market_enabled = True
        self.xyz_config = {}
        self._load_xyz_config()

    def _setup_urls(self):
        if self.config:
            self.base_url = self.config.base_url or self.DEFAULT_REST_URL
            self.ws_url = self.config.ws_url or self.DEFAULT_WS_URL
        else:
            self.base_url = self.DEFAULT_REST_URL
            self.ws_url = self.DEFAULT_WS_URL

    def _load_xyz_config(self):
        config_path = (
            Path(__file__).parent.parent.parent.parent.parent
            / "config"
            / "exchanges"
            / "tradexyz_config.yaml"
        )

        try:
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as file:
                    self.xyz_config = yaml.safe_load(file) or {}

                xyz_settings = self.xyz_config.get("tradexyz", {})
                xyz_market = xyz_settings.get("xyz_market", {})
                self.xyz_market_enabled = xyz_market.get("enabled", True)
            else:
                self.xyz_config = {}
        except Exception as exc:
            self.xyz_config = {}
            if self.logger:
                self.logger.error(f"Failed to load TradeXYZ config: {exc}")

    def is_xyz_symbol(self, symbol: str) -> bool:
        if symbol.startswith(self.XYZ_COIN_PREFIX):
            return True

        base_symbol = self._extract_base_symbol(symbol)
        for assets in self.XYZ_ASSET_CLASSES.values():
            if base_symbol in assets:
                return True
        return False

    def to_xyz_coin(self, symbol: str) -> str:
        if symbol.startswith(self.XYZ_COIN_PREFIX):
            return symbol

        base = self._extract_base_symbol(symbol)
        return f"{self.XYZ_COIN_PREFIX}{base}"

    def from_xyz_coin(self, xyz_coin: str) -> str:
        if xyz_coin.startswith(self.XYZ_COIN_PREFIX):
            return xyz_coin[len(self.XYZ_COIN_PREFIX) :]
        return xyz_coin

    def _extract_base_symbol(self, symbol: str) -> str:
        if symbol.startswith(self.XYZ_COIN_PREFIX):
            symbol = symbol[len(self.XYZ_COIN_PREFIX) :]

        if "/" in symbol:
            symbol = symbol.split("/")[0]

        return symbol.upper()

    def to_tradexyz_symbol(self, symbol: str) -> str:
        if self.is_xyz_symbol(symbol):
            base = self._extract_base_symbol(symbol)
            return f"{base}/USD:PERP"
        return symbol

    def map_symbol(self, symbol: str) -> str:
        if self.is_xyz_symbol(symbol):
            return self.to_tradexyz_symbol(symbol)
        return super().map_symbol(symbol)

    def reverse_map_symbol(self, exchange_symbol: str) -> str:
        if exchange_symbol.startswith(self.XYZ_COIN_PREFIX):
            return self.from_xyz_coin(exchange_symbol)

        if exchange_symbol.endswith("/USD:PERP"):
            base_symbol = exchange_symbol.split("/")[0]
            if self.is_xyz_symbol(base_symbol):
                return base_symbol

        return super().reverse_map_symbol(exchange_symbol)

    def get_xyz_asset_list(self) -> List[str]:
        all_assets: List[str] = []
        for assets in self.XYZ_ASSET_CLASSES.values():
            all_assets.extend(assets)
        return all_assets

    def get_supported_xyz_symbols(self) -> List[str]:
        return [asset for asset in self.get_xyz_asset_list() if "/" not in asset]

    def get_xyz_assets_by_class(self, asset_class: str) -> List[str]:
        return self.XYZ_ASSET_CLASSES.get(asset_class, [])

    def get_market_type_from_symbol(self, symbol: str) -> str:
        if self.is_xyz_symbol(symbol):
            return "xyz_perpetual"
        return super().get_market_type_from_symbol(symbol)
