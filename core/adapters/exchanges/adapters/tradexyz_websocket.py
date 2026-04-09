"""
TradeXYZ WebSocket support.

TradeXYZ shares Hyperliquid's WebSocket endpoint, but XYZ market data lives
behind the `dex="xyz"` subscription parameter and uses `xyz:`-prefixed coins.
This module keeps the implementation intentionally small and only covers the
behaviour that the adapter layer needs.
"""

import asyncio
import inspect
import json
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import websockets

from ..interface import ExchangeConfig
from ..models import OrderBookData, OrderBookLevel, OrderSide, TickerData, TradeData
from .tradexyz_base import TradeXYZBase


class TradeXYZWebSocket:
    """WebSocket client for mixed Hyperliquid + TradeXYZ market data."""

    def __init__(self, config: ExchangeConfig, base_instance: TradeXYZBase):
        self.config = config
        self._base = base_instance
        self.logger = base_instance.logger

        self._ws_url = base_instance.ws_url or "wss://api.hyperliquid.xyz/ws"
        self._xyz_ws = None
        self._xyz_ws_connected = False
        self._should_stop = False

        self._message_handler_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        self._individual_callbacks: Dict[str, List[Tuple[str, Callable]]] = {
            "ticker": [],
            "orderbook": [],
            "trades": [],
            "user_data": [],
        }

        self._ticker_symbols: Set[str] = set()
        self._orderbook_symbols: Set[str] = set()
        self._trade_symbols: Set[str] = set()

        self.ticker_callback: Optional[Callable] = None
        self.orderbook_callback: Optional[Callable] = None
        self.trades_callback: Optional[Callable] = None

        self._active_subscriptions: Set[str] = set()
        self._last_heartbeat = 0.0
        self._reconnect_attempts = 0
        self._reconnecting = False

        self._ticker_cache: Dict[str, TickerData] = {}
        self._orderbook_cache: Dict[str, OrderBookData] = {}

        self._message_count = 0
        self._callback_count = 0

    async def connect(self) -> bool:
        """Connect to the shared Hyperliquid WebSocket endpoint."""
        try:
            if self._xyz_ws_connected:
                return True

            if self.logger:
                self.logger.info(f"Connecting TradeXYZ WebSocket: {self._ws_url}")

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self._xyz_ws = await asyncio.wait_for(
                        websockets.connect(
                            self._ws_url,
                            ping_interval=None,
                            ping_timeout=None,
                            close_timeout=10,
                        ),
                        timeout=15,
                    )

                    self._xyz_ws_connected = True
                    self._should_stop = False
                    self._last_heartbeat = time.time()

                    self._message_handler_task = asyncio.create_task(
                        self._message_handler()
                    )
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    await self._resubscribe_all()

                    if self.logger:
                        self.logger.info("TradeXYZ WebSocket connected")

                    return True
                except (asyncio.TimeoutError, Exception) as exc:
                    if self.logger:
                        self.logger.warning(
                            f"TradeXYZ WebSocket connect attempt "
                            f"{attempt + 1}/{max_retries} failed: {exc}"
                        )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)

            return False
        except Exception as exc:
            if self.logger:
                self.logger.error(f"TradeXYZ WebSocket connect error: {exc}")
            return False

    async def disconnect(self) -> None:
        """Close the WebSocket connection and stop background tasks."""
        self._should_stop = True

        for task in (self._message_handler_task, self._heartbeat_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._xyz_ws:
            try:
                await self._xyz_ws.close()
            finally:
                self._xyz_ws = None

        self._xyz_ws_connected = False
        self._active_subscriptions.clear()
        self._ticker_cache.clear()
        self._orderbook_cache.clear()

        if self.logger:
            self.logger.info("TradeXYZ WebSocket disconnected")

    async def subscribe_ticker(self, symbol: str, callback: Callable) -> None:
        """Subscribe to ticker updates for a single symbol."""
        self._ticker_symbols.add(symbol)
        self._individual_callbacks["ticker"].append((symbol, callback))

        if self._xyz_ws_connected:
            if self._base.is_xyz_symbol(symbol):
                await self._subscribe_xyz_allmids()
            else:
                await self._subscribe_allmids()

    async def subscribe_orderbook(self, symbol: str, callback: Callable) -> None:
        """Subscribe to orderbook updates for a single symbol."""
        self._orderbook_symbols.add(symbol)
        self._individual_callbacks["orderbook"].append((symbol, callback))

        if self._xyz_ws_connected:
            coin = self._coin_from_symbol(symbol)
            if self._base.is_xyz_symbol(symbol):
                await self._subscribe_xyz_l2book(coin)
            else:
                await self._subscribe_l2book(coin)

    async def subscribe_trades(self, symbol: str, callback: Callable) -> None:
        """Subscribe to trade updates for a single symbol."""
        self._trade_symbols.add(symbol)
        self._individual_callbacks["trades"].append((symbol, callback))

        if self._xyz_ws_connected:
            await self._subscribe_trades_channel(self._coin_from_symbol(symbol))

    async def subscribe_user_data(self, callback: Callable) -> None:
        """Subscribe to order/fill style user data updates."""
        self._individual_callbacks["user_data"].append(("all", callback))

        if self._xyz_ws_connected:
            await self._subscribe_user_events()

    async def batch_subscribe_tickers(
        self, symbols: List[str], callback: Optional[Callable]
    ) -> None:
        """Subscribe to multiple ticker streams with one shared callback."""
        if not symbols:
            return

        self.ticker_callback = callback
        self._ticker_symbols.update(symbols)

        if self._xyz_ws_connected:
            if any(not self._base.is_xyz_symbol(symbol) for symbol in symbols):
                await self._subscribe_allmids()
            if any(self._base.is_xyz_symbol(symbol) for symbol in symbols):
                await self._subscribe_xyz_allmids()

    async def batch_subscribe_orderbooks(
        self, symbols: List[str], callback: Optional[Callable]
    ) -> None:
        """Subscribe to multiple orderbooks with one shared callback."""
        if not symbols:
            return

        self.orderbook_callback = callback
        self._orderbook_symbols.update(symbols)

        if not self._xyz_ws_connected:
            return

        for symbol in symbols:
            coin = self._coin_from_symbol(symbol)
            if self._base.is_xyz_symbol(symbol):
                await self._subscribe_xyz_l2book(coin)
            else:
                await self._subscribe_l2book(coin)

    async def unsubscribe(self, symbol: Optional[str] = None) -> None:
        """Forget local subscriptions for one symbol or all symbols."""
        if symbol is None:
            await self.unsubscribe_all()
            return

        self._ticker_symbols.discard(symbol)
        self._orderbook_symbols.discard(symbol)
        self._trade_symbols.discard(symbol)

        for key in ("ticker", "orderbook", "trades"):
            self._individual_callbacks[key] = [
                item for item in self._individual_callbacks[key] if item[0] != symbol
            ]

        if not self._ticker_symbols:
            self.ticker_callback = None
        if not self._orderbook_symbols:
            self.orderbook_callback = None
        if not self._trade_symbols:
            self.trades_callback = None

    async def unsubscribe_all(self) -> None:
        """Clear all local subscription state."""
        self._ticker_symbols.clear()
        self._orderbook_symbols.clear()
        self._trade_symbols.clear()

        self._individual_callbacks = {
            "ticker": [],
            "orderbook": [],
            "trades": [],
            "user_data": [],
        }

        self.ticker_callback = None
        self.orderbook_callback = None
        self.trades_callback = None

    async def _send_ws(self, message: Dict[str, Any]) -> None:
        if not self._xyz_ws or not self._xyz_ws_connected:
            return

        await self._xyz_ws.send(json.dumps(message))

    async def _subscribe_allmids(self) -> None:
        sub_key = "allMids"
        if sub_key in self._active_subscriptions:
            return

        await self._send_ws(
            {"method": "subscribe", "subscription": {"type": "allMids"}}
        )
        self._active_subscriptions.add(sub_key)

    async def _subscribe_xyz_allmids(self) -> None:
        sub_key = "allMids_xyz"
        if sub_key in self._active_subscriptions:
            return

        await self._send_ws(
            {
                "method": "subscribe",
                "subscription": {"type": "allMids", "dex": "xyz"},
            }
        )
        self._active_subscriptions.add(sub_key)

    async def _subscribe_l2book(self, coin: str) -> None:
        sub_key = f"l2Book_{coin}"
        if sub_key in self._active_subscriptions:
            return

        await self._send_ws(
            {
                "method": "subscribe",
                "subscription": {"type": "l2Book", "coin": coin},
            }
        )
        self._active_subscriptions.add(sub_key)

    async def _subscribe_xyz_l2book(self, xyz_coin: str) -> None:
        sub_key = f"l2Book_{xyz_coin}"
        if sub_key in self._active_subscriptions:
            return

        await self._send_ws(
            {
                "method": "subscribe",
                "subscription": {"type": "l2Book", "coin": xyz_coin, "dex": "xyz"},
            }
        )
        self._active_subscriptions.add(sub_key)

    async def _subscribe_trades_channel(self, coin: str) -> None:
        sub_key = f"trades_{coin}"
        if sub_key in self._active_subscriptions:
            return

        await self._send_ws(
            {
                "method": "subscribe",
                "subscription": {"type": "trades", "coin": coin},
            }
        )
        self._active_subscriptions.add(sub_key)

    async def _subscribe_user_events(self) -> None:
        if not self.config or not self.config.wallet_address:
            return

        for sub_key, sub_type in (
            ("orderUpdates", "orderUpdates"),
            ("userFills", "userFills"),
        ):
            if sub_key in self._active_subscriptions:
                continue

            await self._send_ws(
                {
                    "method": "subscribe",
                    "subscription": {
                        "type": sub_type,
                        "user": self.config.wallet_address,
                    },
                }
            )
            self._active_subscriptions.add(sub_key)

    async def _message_handler(self) -> None:
        try:
            while not self._should_stop:
                try:
                    if not self._xyz_ws:
                        break

                    message = await asyncio.wait_for(self._xyz_ws.recv(), timeout=60)
                    self._last_heartbeat = time.time()
                    self._message_count += 1
                    await self._process_message(message)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    if not self._should_stop:
                        await self._reconnect()
                    break
                except Exception as exc:
                    if self.logger:
                        self.logger.error(f"TradeXYZ WebSocket receive error: {exc}")
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def _process_message(self, raw_message: str) -> None:
        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            if self.logger:
                self.logger.warning(f"TradeXYZ invalid JSON: {raw_message[:120]}")
            return

        channel = payload.get("channel")
        data = payload.get("data")

        if channel == "allMids":
            await self._handle_all_mids(data)
        elif channel == "l2Book":
            await self._handle_l2book(data)
        elif channel == "trades":
            await self._handle_trades(data)
        elif channel == "orderUpdates":
            await self._handle_order_updates(data)
        elif channel == "userFills":
            await self._handle_user_fills(data)

    async def _handle_all_mids(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return

        mids = data.get("mids", data)
        for coin, mid_price in mids.items():
            symbol = self._resolve_subscribed_symbol(coin, self._ticker_symbols)
            if symbol is None:
                continue

            try:
                price = Decimal(str(mid_price))
                is_xyz = coin.startswith(self._base.XYZ_COIN_PREFIX)
                base_currency = (
                    self._base.from_xyz_coin(coin) if is_xyz else coin
                )

                ticker = TickerData(
                    symbol=symbol,
                    bid=price,
                    ask=price,
                    bid_size=None,
                    ask_size=None,
                    last=price,
                    open=None,
                    high=None,
                    low=None,
                    close=price,
                    volume=None,
                    quote_volume=None,
                    trades_count=None,
                    change=None,
                    percentage=None,
                    funding_rate=None,
                    predicted_funding_rate=None,
                    funding_time=None,
                    next_funding_time=None,
                    funding_interval=None,
                    index_price=None,
                    mark_price=None,
                    oracle_price=None,
                    open_interest=None,
                    open_interest_value=None,
                    delivery_date=None,
                    high_time=None,
                    low_time=None,
                    start_time=None,
                    end_time=None,
                    contract_id=None,
                    contract_name=symbol,
                    base_currency=base_currency,
                    quote_currency="USD" if is_xyz else "USDC",
                    contract_size=None,
                    tick_size=None,
                    lot_size=None,
                    timestamp=datetime.now(),
                    exchange_timestamp=None,
                    received_timestamp=datetime.now(),
                    processed_timestamp=None,
                    sent_timestamp=None,
                    raw_data={"coin": coin, "mid": str(mid_price)},
                )

                self._ticker_cache[symbol] = ticker
                await self._trigger_market_callbacks("ticker", symbol, ticker)
            except Exception as exc:
                if self.logger and self._message_count % 1000 == 0:
                    self.logger.error(f"TradeXYZ ticker parse error ({coin}): {exc}")

    async def _handle_l2book(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return

        coin = data.get("coin", "")
        symbol = self._resolve_subscribed_symbol(coin, self._orderbook_symbols)
        if symbol is None:
            return

        levels = data.get("levels", [[], []])
        bids_raw = levels[0] if len(levels) > 0 else []
        asks_raw = levels[1] if len(levels) > 1 else []

        bids = [
            OrderBookLevel(
                price=Decimal(str(level.get("px", "0"))),
                size=Decimal(str(level.get("sz", "0"))),
            )
            for level in bids_raw
        ]
        asks = [
            OrderBookLevel(
                price=Decimal(str(level.get("px", "0"))),
                size=Decimal(str(level.get("sz", "0"))),
            )
            for level in asks_raw
        ]

        orderbook = OrderBookData(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(),
            nonce=data.get("time"),
            raw_data=data,
        )

        self._orderbook_cache[symbol] = orderbook
        await self._trigger_market_callbacks("orderbook", symbol, orderbook)

    async def _handle_trades(self, data: Any) -> None:
        if not data:
            return

        trades = data if isinstance(data, list) else [data]
        for trade_info in trades:
            coin = trade_info.get("coin", "")
            symbol = self._resolve_subscribed_symbol(coin, self._trade_symbols)
            if symbol is None:
                continue

            amount = Decimal(str(trade_info.get("sz", "0")))
            price = Decimal(str(trade_info.get("px", "0")))

            trade = TradeData(
                id=str(trade_info.get("tid", "")),
                symbol=symbol,
                side=(
                    OrderSide.BUY if trade_info.get("side") == "B" else OrderSide.SELL
                ),
                amount=amount,
                price=price,
                cost=amount * price,
                fee=None,
                timestamp=datetime.now(),
                order_id=None,
                raw_data=trade_info,
            )

            await self._trigger_market_callbacks("trades", symbol, trade)

    async def _handle_order_updates(self, data: Any) -> None:
        await self._trigger_user_data_callbacks(
            {"type": "order_update", "data": data}
        )

    async def _handle_user_fills(self, data: Any) -> None:
        await self._trigger_user_data_callbacks({"type": "user_fill", "data": data})

    async def _trigger_market_callbacks(
        self, sub_type: str, symbol: str, data: Any
    ) -> None:
        batch_callback = None
        if sub_type == "ticker":
            batch_callback = self.ticker_callback
        elif sub_type == "orderbook":
            batch_callback = self.orderbook_callback
        elif sub_type == "trades":
            batch_callback = self.trades_callback

        if batch_callback:
            await self._invoke_callback(batch_callback, symbol, data)

        for subscribed_symbol, callback in self._individual_callbacks[sub_type]:
            if subscribed_symbol == symbol or subscribed_symbol == "all":
                await self._invoke_callback(callback, symbol, data)

    async def _trigger_user_data_callbacks(self, data: Any) -> None:
        for _, callback in self._individual_callbacks["user_data"]:
            await self._invoke_callback(callback, "all", data)

    async def _invoke_callback(self, callback: Callable, symbol: str, data: Any) -> None:
        try:
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
            self._callback_count += 1
        except Exception as exc:
            if self.logger:
                self.logger.error(f"TradeXYZ callback error ({symbol}): {exc}")

    def _get_callback_param_count(self, callback: Callable) -> int:
        try:
            return len(inspect.signature(callback).parameters)
        except (TypeError, ValueError):
            return 2

    async def _heartbeat_loop(self) -> None:
        try:
            while not self._should_stop:
                await asyncio.sleep(30)

                if self._xyz_ws and self._xyz_ws_connected:
                    try:
                        await self._send_ws({"method": "ping"})
                    except Exception:
                        if not self._should_stop:
                            await self._reconnect()
                        return

                if time.time() - self._last_heartbeat > 120:
                    if not self._should_stop:
                        await self._reconnect()
                    return
        except asyncio.CancelledError:
            pass

    async def _reconnect(self) -> None:
        if self._reconnecting or self._should_stop:
            return

        self._reconnecting = True
        self._reconnect_attempts += 1

        try:
            if self._xyz_ws:
                try:
                    await self._xyz_ws.close()
                except Exception:
                    pass
                self._xyz_ws = None

            self._xyz_ws_connected = False
            self._active_subscriptions.clear()

            await asyncio.sleep(min(5 * self._reconnect_attempts, 30))

            if await self.connect():
                self._reconnect_attempts = 0
        finally:
            self._reconnecting = False

    async def _resubscribe_all(self) -> None:
        self._active_subscriptions.clear()

        if any(not self._base.is_xyz_symbol(symbol) for symbol in self._ticker_symbols):
            await self._subscribe_allmids()
        if any(self._base.is_xyz_symbol(symbol) for symbol in self._ticker_symbols):
            await self._subscribe_xyz_allmids()

        for symbol in sorted(self._orderbook_symbols):
            coin = self._coin_from_symbol(symbol)
            if self._base.is_xyz_symbol(symbol):
                await self._subscribe_xyz_l2book(coin)
            else:
                await self._subscribe_l2book(coin)

        for symbol in sorted(self._trade_symbols):
            await self._subscribe_trades_channel(self._coin_from_symbol(symbol))

        if self._individual_callbacks["user_data"]:
            await self._subscribe_user_events()

    def _coin_from_symbol(self, symbol: str) -> str:
        if self._base.is_xyz_symbol(symbol):
            return self._base.to_xyz_coin(symbol)

        if "/" in symbol:
            return symbol.split("/")[0]
        return symbol

    def _symbol_candidates_from_coin(self, coin: str) -> List[str]:
        if coin.startswith(self._base.XYZ_COIN_PREFIX):
            base_symbol = self._base.from_xyz_coin(coin)
            return [base_symbol, f"{base_symbol}/USD:PERP", coin]

        return [f"{coin}/USDC:USDC", coin, f"{coin}/USDC:PERP"]

    def _resolve_subscribed_symbol(
        self, coin: str, subscribed_symbols: Set[str]
    ) -> Optional[str]:
        for candidate in self._symbol_candidates_from_coin(coin):
            if candidate in subscribed_symbols:
                return candidate
        return None

    def get_cached_ticker(self, symbol: str) -> Optional[TickerData]:
        return self._ticker_cache.get(symbol)

    def get_cached_orderbook(self, symbol: str) -> Optional[OrderBookData]:
        return self._orderbook_cache.get(symbol)

    def is_connected(self) -> bool:
        return self._xyz_ws_connected and self._xyz_ws is not None

    def get_connection_status(self) -> Dict[str, Any]:
        return {
            "connected": self.is_connected(),
            "subscriptions": len(self._active_subscriptions),
            "ticker_symbols": len(self._ticker_symbols),
            "orderbook_symbols": len(self._orderbook_symbols),
            "trade_symbols": len(self._trade_symbols),
            "user_data_callbacks": len(self._individual_callbacks["user_data"]),
            "reconnect_attempts": self._reconnect_attempts,
            "message_count": self._message_count,
            "callback_count": self._callback_count,
            "last_heartbeat": self._last_heartbeat,
            "ws_url": self._ws_url,
        }
