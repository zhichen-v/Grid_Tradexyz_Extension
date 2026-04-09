"""
TradeXYZ exchange adapter.

The adapter follows the same public interface as the other exchange modules in
this repository and composes the TradeXYZ base/rest/websocket helpers.
"""

import asyncio
import inspect
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from ..adapter import ExchangeAdapter
from ..interface import ExchangeConfig
from ..models import (
    BalanceData,
    ExchangeInfo,
    OHLCVData,
    OrderBookData,
    OrderData,
    OrderSide,
    OrderType,
    PositionData,
    TickerData,
    TradeData,
)
from ..subscription_manager import DataType, create_subscription_manager
from .tradexyz_base import TradeXYZBase
from .tradexyz_rest import TradeXYZRest
from .tradexyz_websocket import TradeXYZWebSocket


class TradeXYZAdapter(ExchangeAdapter):
    """Main adapter that exposes TradeXYZ via the shared exchange interface."""

    def __init__(self, config: ExchangeConfig, event_bus=None):
        super().__init__(config, event_bus)

        self._base = TradeXYZBase(config)
        self._rest = TradeXYZRest(config, None)
        self._websocket = TradeXYZWebSocket(config, self._base)

        self._base.set_logger(self.logger)
        self._rest.logger = self.logger
        self._websocket.logger = self.logger

        self._supported_symbols: List[str] = []
        self._ws_callbacks: Dict[str, List[Any]] = {
            "ticker": [],
            "orderbook": [],
            "trades": [],
            "user_data": [],
        }

        try:
            self._tradexyz_config = self._load_tradexyz_config()
            symbol_cache_service = self._get_symbol_cache_service()
            self._subscription_manager = create_subscription_manager(
                exchange_config=self._tradexyz_config,
                symbol_cache_service=symbol_cache_service,
                logger=self.logger,
            )
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    f"TradeXYZ subscription config load failed, using fallback: {exc}"
                )

            self._tradexyz_config = {
                "exchange_id": "tradexyz",
                "subscription_mode": {
                    "mode": "predefined",
                    "predefined": {
                        "symbols": [
                            "BTC/USDC:USDC",
                            "ETH/USDC:USDC",
                            "SOL/USDC:USDC",
                            "TSLA",
                            "AAPL",
                            "NVDA",
                            "SP500",
                        ],
                        "data_types": {
                            "ticker": True,
                            "orderbook": True,
                            "trades": False,
                            "user_data": False,
                        },
                    },
                },
            }
            self._subscription_manager = create_subscription_manager(
                exchange_config=self._tradexyz_config,
                symbol_cache_service=self._get_symbol_cache_service(),
                logger=self.logger,
            )

    def _load_tradexyz_config(self) -> Dict[str, Any]:
        config_path = (
            Path(__file__).parent.parent.parent.parent.parent
            / "config"
            / "exchanges"
            / "tradexyz_config.yaml"
        )

        if not config_path.exists():
            raise FileNotFoundError(f"TradeXYZ config not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as file:
            config_data = yaml.safe_load(file) or {}

        tradexyz_config = config_data.get("tradexyz", {})
        tradexyz_config["exchange_id"] = "tradexyz"
        return tradexyz_config

    async def _do_connect(self) -> bool:
        if not await self._rest.connect():
            return False

        await self._fetch_supported_symbols()

        if self.config.enable_websocket:
            return await self._websocket.connect()

        return True

    async def _do_disconnect(self) -> None:
        await self._websocket.disconnect()
        await self._rest.disconnect()

        for callbacks in self._ws_callbacks.values():
            callbacks.clear()

    async def _do_authenticate(self) -> bool:
        if not self.config.api_key:
            if self.logger:
                self.logger.info("TradeXYZ running in public/read-only mode")
            return True

        if not self.config.wallet_address:
            if self.logger:
                self.logger.warning("TradeXYZ authentication requires wallet_address")
            return False

        return True

    async def _do_health_check(self) -> Dict[str, Any]:
        exchange_info = await self._rest.get_exchange_info()
        return {
            "exchange_time": exchange_info.timestamp,
            "rest_connected": self._rest.exchange is not None,
            "websocket_connected": self._websocket.is_connected(),
            "market_count": len(await self.get_supported_symbols()),
            "subscriptions": self._websocket.get_connection_status().get(
                "subscriptions", 0
            ),
        }

    async def _do_heartbeat(self) -> None:
        if self.config.enable_websocket and not self._websocket.is_connected():
            if self.logger:
                self.logger.warning(
                    "TradeXYZ WebSocket is disconnected during heartbeat"
                )

    async def get_exchange_info(self) -> ExchangeInfo:
        return await self._rest.get_exchange_info()

    async def get_ticker(self, symbol: str) -> TickerData:
        return await self._rest.get_ticker(symbol)

    async def get_tickers(
        self, symbols: Optional[List[str]] = None
    ) -> List[TickerData]:
        target_symbols = symbols or await self.get_supported_symbols()
        return await asyncio.gather(*(self.get_ticker(symbol) for symbol in target_symbols))

    async def get_orderbook(
        self, symbol: str, limit: Optional[int] = None
    ) -> OrderBookData:
        return await self._rest.get_orderbook(symbol, limit)

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[OHLCVData]:
        return await self._rest.get_ohlcv(symbol, timeframe, since, limit)

    async def get_trades(
        self,
        symbol: str,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[TradeData]:
        return await self._rest.get_trades(symbol, since, limit)

    async def get_balances(self) -> List[BalanceData]:
        return await self._rest.get_balances()

    async def get_positions(
        self, symbols: Optional[List[str]] = None
    ) -> List[PositionData]:
        return await self._rest.get_positions(symbols)

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount,
        price=None,
        params: Optional[Dict[str, Any]] = None,
        batch_mode: bool = False,
    ) -> OrderData:
        order = await self._rest.create_order(
            symbol, side, order_type, amount, price, params
        )
        await self._handle_order_update(order)
        return order

    async def cancel_order(self, order_id: str, symbol: str) -> OrderData:
        order = await self._rest.cancel_order(order_id, symbol)
        await self._handle_order_update(order)
        return order

    async def cancel_all_orders(
        self, symbol: Optional[str] = None
    ) -> List[OrderData]:
        orders = await self._rest.cancel_all_orders(symbol)
        for order in orders:
            await self._handle_order_update(order)
        return orders

    async def get_order(self, order_id: str, symbol: str) -> OrderData:
        return await self._rest.get_order(order_id, symbol)

    async def get_open_orders(
        self, symbol: Optional[str] = None
    ) -> List[OrderData]:
        return await self._rest.get_open_orders(symbol)

    async def get_order_history(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[OrderData]:
        return await self._rest.get_order_history(symbol, since, limit)

    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        return await self._rest.set_leverage(symbol, leverage)

    async def set_margin_mode(
        self, symbol: str, margin_mode: str
    ) -> Dict[str, Any]:
        return await self._rest.set_margin_mode(symbol, margin_mode)

    async def subscribe_ticker(self, symbol: str, callback: Callable) -> None:
        await self._ensure_websocket_connection()
        wrapped = self._wrap_market_callback(callback, self._handle_ticker_update)
        self._ws_callbacks["ticker"].append((symbol, callback, wrapped))
        await self._websocket.subscribe_ticker(symbol, wrapped)

    async def subscribe_orderbook(self, symbol: str, callback: Callable) -> None:
        await self._ensure_websocket_connection()
        wrapped = self._wrap_market_callback(
            callback, self._handle_orderbook_update
        )
        self._ws_callbacks["orderbook"].append((symbol, callback, wrapped))
        await self._websocket.subscribe_orderbook(symbol, wrapped)

    async def subscribe_trades(self, symbol: str, callback: Callable) -> None:
        await self._ensure_websocket_connection()
        wrapped = self._wrap_market_callback(callback, None)
        self._ws_callbacks["trades"].append((symbol, callback, wrapped))
        await self._websocket.subscribe_trades(symbol, wrapped)

    async def subscribe_user_data(self, callback: Callable) -> None:
        await self._ensure_websocket_connection()
        wrapped = self._wrap_user_data_callback(callback)
        self._ws_callbacks["user_data"].append(("all", callback, wrapped))
        await self._websocket.subscribe_user_data(wrapped)

    async def unsubscribe(self, symbol: Optional[str] = None) -> None:
        await self._websocket.unsubscribe(symbol)
        self._cleanup_callback_registry(symbol)

    async def unsubscribe_all(self) -> None:
        await self._websocket.unsubscribe_all()
        self._cleanup_callback_registry(None)

    async def batch_subscribe_tickers(
        self,
        symbols: Optional[List[str]] = None,
        callback: Optional[Callable[[str, TickerData], None]] = None,
    ) -> None:
        if not self._subscription_manager.should_subscribe_data_type(DataType.TICKER):
            return

        resolved_symbols = await self._resolve_batch_symbols(symbols)
        if not resolved_symbols:
            return

        await self._ensure_websocket_connection()

        noop = callback or (lambda *_args, **_kwargs: None)
        wrapped = self._wrap_market_callback(noop, self._handle_ticker_update)

        for symbol in resolved_symbols:
            self._subscription_manager.add_subscription(
                symbol=symbol, data_type=DataType.TICKER, callback=wrapped
            )
            self._ws_callbacks["ticker"].append((symbol, callback, wrapped))

        await self._websocket.batch_subscribe_tickers(resolved_symbols, wrapped)

    async def batch_subscribe_orderbooks(
        self,
        symbols: Optional[List[str]] = None,
        callback: Optional[Callable[[str, OrderBookData], None]] = None,
    ) -> None:
        if not self._subscription_manager.should_subscribe_data_type(
            DataType.ORDERBOOK
        ):
            return

        resolved_symbols = await self._resolve_batch_symbols(symbols)
        if not resolved_symbols:
            return

        await self._ensure_websocket_connection()

        noop = callback or (lambda *_args, **_kwargs: None)
        wrapped = self._wrap_market_callback(noop, self._handle_orderbook_update)

        for symbol in resolved_symbols:
            self._subscription_manager.add_subscription(
                symbol=symbol, data_type=DataType.ORDERBOOK, callback=wrapped
            )
            self._ws_callbacks["orderbook"].append((symbol, callback, wrapped))

        await self._websocket.batch_subscribe_orderbooks(resolved_symbols, wrapped)

    async def _resolve_batch_symbols(
        self, symbols: Optional[List[str]]
    ) -> List[str]:
        if symbols is not None:
            return list(symbols)

        if self._subscription_manager.mode.value == "predefined":
            return self._subscription_manager.get_subscription_symbols()

        return await self._subscription_manager.discover_symbols(
            self.get_supported_symbols
        )

    async def get_supported_symbols(self) -> List[str]:
        if self._supported_symbols:
            return self._supported_symbols.copy()

        await self._fetch_supported_symbols()
        return self._supported_symbols.copy()

    async def _fetch_supported_symbols(self) -> None:
        crypto_symbols: List[str] = []

        if self._rest.exchange and hasattr(self._rest.exchange, "markets"):
            for symbol, market_info in self._rest.exchange.markets.items():
                market_type = market_info.get("type")
                if market_info.get("swap") or market_type in {"swap", "future"}:
                    crypto_symbols.append(symbol)

            if not crypto_symbols:
                crypto_symbols = list(self._rest.exchange.markets.keys())

        xyz_symbols = [
            asset for asset in self._base.get_xyz_asset_list() if "/" not in asset
        ]

        extra_symbols = (
            self._tradexyz_config.get("symbols", {}).get("xyz", [])
            if isinstance(self._tradexyz_config.get("symbols"), dict)
            else []
        )

        merged: List[str] = []
        seen = set()
        for symbol in crypto_symbols + xyz_symbols + extra_symbols:
            if symbol not in seen:
                merged.append(symbol)
                seen.add(symbol)

        self._supported_symbols = merged
        self._base._supported_symbols = merged

    def get_connection_status(self) -> Dict[str, Any]:
        return {
            "rest_connected": self._rest.exchange is not None,
            "websocket_status": self._websocket.get_connection_status(),
            "total_subscriptions": sum(
                len(callbacks) for callbacks in self._ws_callbacks.values()
            ),
        }

    def map_symbol(self, symbol: str) -> str:
        return self._base.map_symbol(symbol)

    def reverse_map_symbol(self, exchange_symbol: str) -> str:
        return self._base.reverse_map_symbol(exchange_symbol)

    def get_subscription_manager(self):
        return self._subscription_manager

    def get_subscription_stats(self) -> Dict[str, Any]:
        return self._subscription_manager.get_subscription_stats()

    async def _ensure_websocket_connection(self) -> None:
        if not self.config.enable_websocket:
            raise RuntimeError("TradeXYZ WebSocket is disabled in config")

        if not self._websocket.is_connected():
            connected = await self._websocket.connect()
            if not connected:
                raise ConnectionError("Failed to connect TradeXYZ WebSocket")

    def _wrap_market_callback(
        self,
        callback: Callable,
        post_handler: Optional[Callable[[Any], Any]],
    ) -> Callable[[str, Any], Any]:
        async def wrapped(symbol: str, data: Any):
            await self._invoke_callback(callback, symbol, data)
            if post_handler:
                await post_handler(data)

        return wrapped

    def _wrap_user_data_callback(self, callback: Callable) -> Callable[[str, Any], Any]:
        async def wrapped(symbol: str, data: Any):
            await self._invoke_callback(callback, symbol, data)

        return wrapped

    async def _invoke_callback(self, callback: Callable, symbol: str, data: Any) -> None:
        param_count = self._get_callback_param_count(callback)

        if asyncio.iscoroutinefunction(callback):
            if param_count >= 2:
                await callback(symbol, data)
            else:
                await callback(data)
        else:
            if param_count >= 2:
                callback(symbol, data)
            else:
                callback(data)

    def _get_callback_param_count(self, callback: Callable) -> int:
        try:
            return len(inspect.signature(callback).parameters)
        except (TypeError, ValueError):
            return 2

    def _cleanup_callback_registry(self, symbol: Optional[str]) -> None:
        if symbol is None:
            for callbacks in self._ws_callbacks.values():
                callbacks.clear()
            return

        for key in ("ticker", "orderbook", "trades"):
            self._ws_callbacks[key] = [
                item for item in self._ws_callbacks[key] if item[0] != symbol
            ]

    def _get_symbol_cache_service(self):
        try:
            from ....di.container import get_container
            from ....services.symbol_manager.interfaces.symbol_cache import (
                ISymbolCacheService,
            )

            container = get_container()
            return container.get(ISymbolCacheService)
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    f"TradeXYZ symbol cache service unavailable: {exc}"
                )
            return None

    @property
    def supported_symbols(self) -> List[str]:
        return self._supported_symbols.copy()

    def __repr__(self) -> str:
        return (
            "TradeXYZAdapter("
            f"connected={self.is_connected()}, "
            f"authenticated={self.is_authenticated()})"
        )
