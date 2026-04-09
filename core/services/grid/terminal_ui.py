"""
网格交易系统终端界面

使用Rich库实现实时监控界面
"""

import asyncio
from typing import Optional
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from ...logging import (
    get_logger,
    set_console_log_level,
    restore_console_log_level,
)
from .models import GridStatistics, GridType
from .models.grid_order import GridOrderStatus, GridOrderSide
from .coordinator import GridCoordinator


class GridTerminalUI:
    """
    网格交易终端界面

    显示内容：
    1. 运行状态
    2. 订单统计
    3. 持仓信息
    4. 盈亏统计
    5. 最近成交订单
    """

    DISPLAY_TIMEZONE = timezone(timedelta(hours=8))

    def __init__(self, coordinator: GridCoordinator):
        """
        初始化终端界面

        Args:
            coordinator: 网格协调器
        """
        self.logger = get_logger(__name__)
        self.coordinator = coordinator
        self.console = Console()
        self.live_console_level = "WARNING"

        # 界面配置
        self.refresh_rate = 2  # 刷新频率（次/秒）- 降低刷新率减少闪烁
        self.history_limit = 10  # 显示历史记录数

        # 运行控制
        self._running = False

        # 提取基础货币名称（从交易对符号中提取）
        # 例如: BTC_USDC_PERP -> BTC, HYPE_USDC_PERP -> HYPE
        symbol = self.coordinator.config.symbol
        self.base_currency = symbol.split('_')[0] if '_' in symbol else symbol

    def create_header(self, stats: GridStatistics) -> Panel:
        """创建标题栏"""
        # 判断网格类型（做多/做空）
        is_long = self.coordinator.config.grid_type in [
            GridType.LONG, GridType.MARTINGALE_LONG, GridType.FOLLOW_LONG]
        grid_type_text = "做多网格" if is_long else "做空网格"

        title = Text()
        title.append("🎯 网格交易系统实时监控 ", style="bold cyan")
        title.append("v2.8", style="bold magenta")
        title.append(" - ", style="bold white")
        title.append(
            f"{self.coordinator.config.exchange.upper()}/", style="bold yellow")
        title.append(f"{self.coordinator.config.symbol}", style="bold green")

        return Panel(title, style="bold white on blue")

    def create_status_panel(self, stats: GridStatistics) -> Panel:
        """创建运行状态面板"""
        # 判断网格类型（做多/做空）和模式（普通/马丁/价格移动）
        grid_type = self.coordinator.config.grid_type

        if grid_type == GridType.LONG:
            grid_type_text = "做多网格（普通）"
        elif grid_type == GridType.SHORT:
            grid_type_text = "做空网格（普通）"
        elif grid_type == GridType.MARTINGALE_LONG:
            grid_type_text = "做多网格（马丁）"
        elif grid_type == GridType.MARTINGALE_SHORT:
            grid_type_text = "做空网格（马丁）"
        elif grid_type == GridType.FOLLOW_LONG:
            grid_type_text = "做多网格（价格移动）"
        elif grid_type == GridType.FOLLOW_SHORT:
            grid_type_text = "做空网格（价格移动）"
        else:
            grid_type_text = grid_type.value

        status_text = self.coordinator.get_status_text()

        # 格式化运行时长
        running_time = str(stats.running_time).split('.')[0]  # 移除微秒

        # 🔥 获取剥头皮模式状态
        scalping_enabled = self.coordinator.config.scalping_enabled
        scalping_active = False
        if self.coordinator.scalping_manager:
            scalping_active = self.coordinator.scalping_manager.is_active()

        # 🛡️ 获取本金保护模式状态
        capital_protection_enabled = self.coordinator.config.capital_protection_enabled
        capital_protection_active = False
        if self.coordinator.capital_protection_manager:
            capital_protection_active = self.coordinator.capital_protection_manager.is_active()

        content = Text()
        content.append(
            f"├─ 网格策略: {grid_type_text} ({stats.grid_count}格)   ", style="white")
        content.append(f"状态: {status_text}", style="bold")
        content.append("\n")

        # 📊 显示马丁模式状态（如果启用）
        if self.coordinator.config.martingale_increment and self.coordinator.config.martingale_increment > 0:
            content.append("├─ 马丁模式: ", style="white")
            content.append("✅ 已启用", style="bold green")
            content.append(f"  |  递增: ", style="white")
            content.append(
                f"{self.coordinator.config.martingale_increment} {self.base_currency}", style="bold yellow")
            content.append("\n")

        # 🔥 显示剥头皮模式状态
        if scalping_enabled:
            content.append("├─ 剥头皮: ", style="white")
            if scalping_active:
                content.append("🔴 已激活", style="bold red")
            else:
                content.append("⚪ 待触发", style="bold cyan")
            # 🆕 显示触发次数（从启动就显示，包括0次）
            content.append(f"  |  触发次数: ", style="white")
            content.append(f"{stats.scalping_trigger_count}",
                           style="bold yellow")
            # 🆕 显示触发网格和价格（从配置文件读取）
            trigger_grid = self.coordinator.config.get_scalping_trigger_grid()
            trigger_price = self.coordinator.config.get_grid_price(
                trigger_grid)
            content.append(f"  |  触发网格: ", style="white")
            content.append(f"Grid {trigger_grid}", style="bold cyan")
            content.append(f"  |  触发价格: ", style="white")
            content.append(f"${trigger_price:,.4f}", style="bold cyan")
            content.append("\n")

        # 🛡️ 显示本金保护模式状态
        if capital_protection_enabled:
            content.append("├─ 本金保护: ", style="white")
            if capital_protection_active:
                content.append("🟢 已触发", style="bold green")
            else:
                content.append("⚪ 待触发", style="bold cyan")
            # 🆕 显示触发次数（从启动就显示，包括0次）
            content.append(f"  |  触发次数: ", style="white")
            content.append(
                f"{stats.capital_protection_trigger_count}", style="bold yellow")
            content.append("\n")

        # 💰 显示止盈模式状态
        if stats.take_profit_enabled:
            content.append("├─ 止盈: ", style="white")
            if stats.take_profit_active:
                content.append("🔴 已触发", style="bold red")
            else:
                # 显示当前盈利率和阈值
                profit_rate = float(stats.take_profit_profit_rate)
                threshold = float(stats.take_profit_threshold)
                content.append("⚪ 待触发  |  ", style="bold cyan")
                if profit_rate >= 0:
                    content.append(
                        f"当前: +{profit_rate:.2f}%  阈值: {threshold:.2f}%", style="bold green")
                else:
                    content.append(
                        f"当前: {profit_rate:.2f}%  阈值: {threshold:.2f}%", style="bold red")
            # 🆕 显示触发次数（从启动就显示，包括0次）
            content.append(f"  |  触发次数: ", style="white")
            content.append(
                f"{stats.take_profit_trigger_count}", style="bold yellow")
            content.append("\n")

        # 🔒 显示价格锁定模式状态
        if stats.price_lock_enabled:
            content.append("├─ 价格锁定: ", style="white")
            if stats.price_lock_active:
                content.append("🔒 已激活 (冻结)", style="bold yellow")
            else:
                threshold = float(stats.price_lock_threshold)
                current = float(stats.current_price)
                content.append("⚪ 待触发  |  ", style="bold cyan")
                content.append(
                    f"当前: ${current:,.2f}  阈值: ${threshold:,.2f}", style="white")
            content.append("\n")

        # 🔄 显示价格脱离倒计时（价格移动网格专用）
        if stats.price_escape_active:
            content.append("├─ 价格脱离: ", style="white")
            direction_text = "⬇️ 向下" if stats.price_escape_direction == "down" else "⬆️ 向上"
            content.append(f"{direction_text} ", style="bold yellow")
            content.append(
                f"⏱️ {stats.price_escape_remaining}s", style="bold red")
            # 🆕 显示触发次数（从启动就显示，包括0次）
            content.append(f"  |  触发次数: ", style="white")
            content.append(
                f"{stats.price_escape_trigger_count}", style="bold yellow")
            content.append("\n")
        # 🆕 即使没有脱离，如果是价格移动网格，也显示历史触发次数
        elif self.coordinator.config.is_follow_mode():
            content.append("├─ 价格脱离: ", style="white")
            content.append("✅ 正常  ", style="bold green")
            content.append(f"|  历史触发次数: ", style="white")
            content.append(
                f"{stats.price_escape_trigger_count}", style="bold yellow")
            content.append("\n")

        content.append(
            f"├─ 价格区间: ${stats.price_range[0]:,.2f} - ${stats.price_range[1]:,.2f}  ", style="white")
        content.append(f"网格间隔: ${stats.grid_interval}  ", style="cyan")
        content.append(
            f"反手距离: {self.coordinator.config.reverse_order_grid_distance}格\n", style="magenta")

        # 🆕 显示单格金额（仅作为显示，无实质功能）
        content.append(f"├─ 单格金额: ", style="white")
        content.append(
            f"{self.coordinator.config.order_amount} {self.base_currency}  ", style="bold cyan")
        content.append(
            f"数量精度: {self.coordinator.config.quantity_precision}位\n", style="white")

        content.append(
            f"├─ 当前价格: ${stats.current_price:,.2f}             ", style="bold yellow")
        content.append(
            f"当前位置: Grid {stats.current_grid_id}/{stats.grid_count}\n", style="white")

        content.append(f"└─ 运行时长: {running_time}", style="white")

        return Panel(content, title="📊 运行状态", border_style="green")

    def _get_display_pending_order_counts(self, stats: GridStatistics) -> tuple[int, int, int]:
        """Return TUI-facing pending counts without changing the real engine totals."""
        display_buy_orders = stats.pending_buy_orders
        display_sell_orders = stats.pending_sell_orders
        position_order_units = self._get_position_order_units(stats.current_position)

        if position_order_units <= 0:
            return display_buy_orders, display_sell_orders, 0

        grid_type = self.coordinator.config.grid_type

        if grid_type in [GridType.LONG, GridType.MARTINGALE_LONG, GridType.FOLLOW_LONG] and stats.current_position > 0:
            display_buy_orders = max(display_buy_orders - position_order_units, 0)
        elif grid_type in [GridType.SHORT, GridType.MARTINGALE_SHORT, GridType.FOLLOW_SHORT] and stats.current_position < 0:
            display_sell_orders = max(display_sell_orders - position_order_units, 0)

        return display_buy_orders, display_sell_orders, position_order_units

    def _get_position_order_units(self, current_position: Decimal) -> int:
        """Convert current position size to whole order units for TUI display."""
        order_amount = self.coordinator.config.order_amount
        if order_amount <= 0:
            return 0

        position_units = (abs(current_position) / order_amount).quantize(
            Decimal('1'),
            rounding=ROUND_DOWN
        )
        return int(position_units)

    def create_orders_panel(self, stats: GridStatistics) -> Panel:
        """创建订单统计面板"""
        content = Text()

        # 🔥 显示监控方式
        monitoring_mode = getattr(stats, 'monitoring_mode', 'WebSocket')
        if monitoring_mode == "WebSocket":
            mode_icon = "📡"
            mode_style = "bold cyan"
        else:
            mode_icon = "📊"
            mode_style = "bold yellow"

        content.append(f"├─ 监控方式: ", style="white")
        content.append(f"{mode_icon} {monitoring_mode}", style=mode_style)
        content.append("\n")

        # 🔥 修复：从实际订单中获取Grid ID范围，而不是基于current_grid_id猜测
        # 这样可以准确显示实际挂单的网格范围
        buy_grid_ids = []
        sell_grid_ids = []

        # 从coordinator的state中获取实际订单
        if hasattr(self.coordinator, 'state') and hasattr(self.coordinator.state, 'active_orders'):
            for order in self.coordinator.state.active_orders.values():
                if hasattr(order, 'grid_id') and order.grid_id:
                    if order.side == GridOrderSide.BUY:
                        buy_grid_ids.append(order.grid_id)
                    elif order.side == GridOrderSide.SELL:
                        sell_grid_ids.append(order.grid_id)

        # 计算买单范围
        if buy_grid_ids:
            min_buy = min(buy_grid_ids)
            max_buy = max(buy_grid_ids)
            buy_range = f"Grid {min_buy}-{max_buy}" if min_buy != max_buy else f"Grid {min_buy}"
        else:
            buy_range = "无"

        # 计算卖单范围
        if sell_grid_ids:
            min_sell = min(sell_grid_ids)
            max_sell = max(sell_grid_ids)
            sell_range = f"Grid {min_sell}-{max_sell}" if min_sell != max_sell else f"Grid {min_sell}"
        else:
            sell_range = "无"

        content.append(
            f"├─ 未成交买单: {stats.pending_buy_orders}个 ({buy_range}) ⏳\n", style="green")
        content.append(
            f"├─ 未成交卖单: {stats.pending_sell_orders}个 ({sell_range}) ⏳\n", style="red")

        # 🔥 显示剥头皮止盈订单（更详细）
        if self.coordinator.config.is_scalping_enabled():
            if self.coordinator.scalping_manager and self.coordinator.scalping_manager.is_active():
                tp_order = self.coordinator.scalping_manager.get_current_take_profit_order()
                if tp_order:
                    content.append(f"├─ 🎯 止盈订单: ", style="white")
                    content.append(
                        f"sell {abs(tp_order.amount):.5f}@${tp_order.price:,.2f} (Grid {tp_order.grid_id})",
                        style="bold yellow"
                    )
                    content.append("\n")
                else:
                    content.append(f"├─ 🎯 止盈订单: ", style="white")
                    content.append("⚠️ 未挂出", style="red")
                    content.append("\n")
            else:
                # 剥头皮模式启用但未激活
                content.append(f"├─ 🎯 止盈订单: ", style="white")
                content.append("⏳ 待触发", style="yellow")
                content.append("\n")

        content.append(
            f"└─ 总挂单数量: {stats.total_pending_orders}个", style="white")

        return Panel(content, title="📋 订单统计", border_style="blue")

    def _calculate_liquidation_price(self, stats: GridStatistics) -> tuple:
        """
        计算爆仓价格（仅作为风险提示，无实质功能）

        核心思路（更简单合理）：
        1. 假设极端情况：所有未成交的方向性订单全部成交
        2. 计算最终持仓和平均成本
        3. 用公式直接求出爆仓价格（净权益 = 0）

        适用于所有模式（包括剥头皮模式）

        爆仓条件: 净权益 ≤ 0
        净权益 = 当前权益 + 持仓未实现盈亏

        Returns:
            (liquidation_price, distance_percent, risk_level)
            - liquidation_price: 爆仓价格（Decimal），None表示无风险
            - distance_percent: 距离当前价格的百分比（float）
            - risk_level: 风险等级 'safe'/'warning'/'danger'/'N/A'
        """
        from decimal import Decimal

        try:
            # 获取未成交订单（从 GridState 的 active_orders 字典获取）
            open_orders = [
                order for order in self.coordinator.state.active_orders.values()
                if order.status == GridOrderStatus.PENDING  # 只获取待成交的订单
            ]

            # 特殊情况: 无持仓且无订单，不计算
            if stats.current_position == 0 and len(open_orders) == 0:
                return (None, 0.0, 'N/A')

            # 获取当前状态
            current_equity = stats.collateral_balance  # 当前权益
            current_position = stats.current_position  # 当前持仓（正数=多，负数=空）
            average_cost = stats.average_cost  # 平均成本
            current_price = stats.current_price  # 当前价格

            # 判断网格类型（基于当前持仓或订单方向）
            if current_position > 0:
                is_long = True
            elif current_position < 0:
                is_long = False
            else:
                # 无持仓，根据订单判断
                buy_orders = [
                    o for o in open_orders if o.side == GridOrderSide.BUY]
                is_long = len(buy_orders) > 0

            if is_long:
                # 做多网格：计算所有买单成交后的爆仓价格
                liquidation_price = self._calculate_long_liquidation(
                    current_equity, current_position, average_cost, open_orders
                )
                if liquidation_price:
                    distance_percent = float(
                        (liquidation_price - current_price) / current_price * 100)
                else:
                    return (None, 0.0, 'safe')  # 权益充足，不会爆仓
            else:
                # 做空网格：计算所有卖单成交后的爆仓价格
                liquidation_price = self._calculate_short_liquidation(
                    current_equity, current_position, average_cost, open_orders
                )
                if liquidation_price:
                    distance_percent = float(
                        (liquidation_price - current_price) / current_price * 100)
                else:
                    return (None, 0.0, 'safe')  # 权益充足，不会爆仓

            # 判断风险等级
            abs_distance = abs(distance_percent)
            if abs_distance > 20:
                risk_level = 'safe'
            elif abs_distance > 10:
                risk_level = 'warning'
            else:
                risk_level = 'danger'

            return (liquidation_price, distance_percent, risk_level)

        except Exception as e:
            self.logger.error(f"计算爆仓价格失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return (None, 0.0, 'N/A')

    def _calculate_long_liquidation(self, equity: Decimal, position: Decimal,
                                    avg_cost: Decimal, open_orders: list) -> Decimal:
        """
        计算做多网格的爆仓价格（极端情况：所有买单成交）

        核心思路：
        1. 假设所有未成交买单全部成交
        2. 计算最终持仓和平均成本
        3. 用公式直接求出爆仓价格

        公式推导：
        净权益 = 0
        equity + final_position × (liquidation_price - final_avg_cost) = 0
        => liquidation_price = final_avg_cost - equity / final_position

        Args:
            equity: 当前权益
            position: 当前持仓数量（正数或0）
            avg_cost: 平均成本
            open_orders: 未成交订单列表

        Returns:
            爆仓价格（Decimal），None表示权益充足不会爆仓
        """
        from decimal import Decimal

        # 获取所有未成交的买单
        buy_orders = [o for o in open_orders if o.side == GridOrderSide.BUY]

        if len(buy_orders) == 0:
            # 无未成交买单
            if position == 0:
                return None  # 无持仓也无订单
            # 有持仓但无订单，直接计算
            liquidation_price = avg_cost - equity / position
            return liquidation_price if liquidation_price > 0 else None

        # 假设所有买单全部成交，计算最终持仓和平均成本
        total_buy_amount = sum(o.amount for o in buy_orders)
        total_buy_cost = sum(o.amount * o.price for o in buy_orders)

        final_position = position + total_buy_amount

        if position > 0:
            # 有初始持仓
            final_avg_cost = (position * avg_cost +
                              total_buy_cost) / final_position
        else:
            # 无初始持仓
            final_avg_cost = total_buy_cost / final_position

        # 计算爆仓价格
        # equity + final_position × (liquidation_price - final_avg_cost) = 0
        # => liquidation_price = final_avg_cost - equity / final_position
        liquidation_price = final_avg_cost - equity / final_position

        # 如果爆仓价格为负数或极小值，表示权益充足
        if liquidation_price <= 0:
            return None

        return liquidation_price

    def _calculate_short_liquidation(self, equity: Decimal, position: Decimal,
                                     avg_cost: Decimal, open_orders: list) -> Decimal:
        """
        计算做空网格的爆仓价格（极端情况：所有卖单成交）

        核心思路：
        1. 假设所有未成交卖单全部成交
        2. 计算最终持仓和平均成本
        3. 用公式直接求出爆仓价格

        公式推导：
        净权益 = 0
        equity + |final_position| × (final_avg_cost - liquidation_price) = 0
        => liquidation_price = final_avg_cost + equity / |final_position|

        Args:
            equity: 当前权益
            position: 当前持仓数量（负数或0）
            avg_cost: 平均成本
            open_orders: 未成交订单列表

        Returns:
            爆仓价格（Decimal），None表示权益充足不会爆仓
        """
        from decimal import Decimal

        # 获取所有未成交的卖单
        sell_orders = [o for o in open_orders if o.side == GridOrderSide.SELL]

        if len(sell_orders) == 0:
            # 无未成交卖单
            if position == 0:
                return None  # 无持仓也无订单
            # 有持仓但无订单，直接计算
            liquidation_price = avg_cost + equity / abs(position)
            return liquidation_price

        # 假设所有卖单全部成交，计算最终持仓和平均成本
        total_sell_amount = sum(o.amount for o in sell_orders)
        total_sell_cost = sum(o.amount * o.price for o in sell_orders)

        position_abs = abs(position)
        final_position_abs = position_abs + total_sell_amount

        if position_abs > 0:
            # 有初始持仓
            final_avg_cost = (position_abs * avg_cost +
                              total_sell_cost) / final_position_abs
        else:
            # 无初始持仓
            final_avg_cost = total_sell_cost / final_position_abs

        # 计算爆仓价格
        # equity + final_position_abs × (final_avg_cost - liquidation_price) = 0
        # => liquidation_price = final_avg_cost + equity / final_position_abs
        liquidation_price = final_avg_cost + equity / final_position_abs

        return liquidation_price

    def create_position_panel(self, stats: GridStatistics) -> Panel:
        """创建持仓信息面板"""
        position_color = "green" if stats.current_position > 0 else "red" if stats.current_position < 0 else "white"
        position_type = "做多" if stats.current_position > 0 else "做空" if stats.current_position < 0 else "空仓"

        content = Text()
        content.append(f"├─ 当前持仓: ", style="white")
        content.append(
            f"{stats.current_position:+.5f} {self.base_currency} ({position_type})      ", style=f"bold {position_color}")

        # 🆕 计算持仓金额（仅作为显示，无实质功能）
        position_value = abs(stats.current_position) * stats.average_cost
        content.append(f"平均成本: ${stats.average_cost:,.2f}  ", style="white")
        content.append(f"持仓金额: ${position_value:,.2f}\n", style="bold cyan")

        # 🔥 显示持仓数据来源（实时）
        data_source = stats.position_data_source
        if "WebSocket" in data_source:
            source_color = "bold green"
            source_icon = "📡"
        elif "REST" in data_source:
            source_color = "bold yellow"
            source_icon = "🔄"
        else:
            source_color = "cyan"
            source_icon = "📊"

        content.append(f"├─ 数据来源: ", style="white")
        content.append(f"{source_icon} {data_source}\n", style=source_color)

        # 💰 基础资金信息（始终显示）
        # 显示初始本金和当前权益
        content.append(
            f"├─ 初始本金: ${stats.initial_capital:,.3f} USDC      ", style="white")
        content.append(
            f"当前权益: ${stats.collateral_balance:,.3f} USDC\n", style="yellow")

        # 计算并显示本金盈亏
        profit_loss = stats.capital_profit_loss
        if profit_loss >= 0:
            pl_sign = "+"
            pl_color = "bold green"
            pl_emoji = "📈"
        else:
            pl_sign = ""
            pl_color = "bold red"
            pl_emoji = "📉"

        profit_loss_rate = (profit_loss / stats.initial_capital *
                            100) if stats.initial_capital > 0 else Decimal('0')
        content.append(f"├─ 本金盈亏: ", style="white")
        content.append(f"{pl_emoji} ", style=pl_color)
        content.append(
            f"{pl_sign}${profit_loss:,.3f} ({pl_sign}{profit_loss_rate:.2f}%)\n",
            style=pl_color
        )

        # 🛡️ 本金保护模式状态
        if stats.capital_protection_enabled:
            # 显示本金保护状态
            if stats.capital_protection_active:
                status_text = "🟢 已触发"
                status_color = "bold green"
            else:
                status_text = "⚪ 待触发"
                status_color = "cyan"

            content.append(f"├─ 本金保护: ", style="white")
            content.append(f"{status_text}\n", style=status_color)

        # 🔒 价格锁定模式状态
        if stats.price_lock_enabled:
            # 显示价格锁定状态
            if stats.price_lock_active:
                status_text = "🔒 已激活（冻结中）"
                status_color = "bold yellow"
            else:
                status_text = "⚪ 待触发"
                status_color = "cyan"

            content.append(f"├─ 价格锁定: ", style="white")
            content.append(f"{status_text}      ", style=status_color)
            content.append(
                f"阈值: ${stats.price_lock_threshold:,.2f}\n", style="white")

        # 💵 余额信息（始终显示）
        content.append(
            f"├─ 现货余额: ${stats.spot_balance:,.2f} USDC      ", style="white")
        content.append(
            f"订单冻结: ${stats.order_locked_balance:,.2f} USDC\n", style="white")

        # 🔥 预留币种信息（仅现货且启用预留时显示）
        if self.coordinator.reserve_manager:
            reserve_status = self.coordinator.reserve_manager.get_status()

            # 状态emoji和颜色
            status_emoji = reserve_status['emoji']  # 🟢/🟡/🔴
            health_percent = reserve_status['health_percent']

            if health_percent >= 50:
                health_color = "bold green"
            elif health_percent >= 30:
                health_color = "bold yellow"
            else:
                health_color = "bold red"

            # 预留信息（动态获取币种名称）
            reserve_amount = reserve_status['reserve_amount']
            current_reserve = reserve_status['current_reserve']
            total_consumed = reserve_status['total_consumed']
            base_currency = self.coordinator.reserve_manager.base_currency

            # 🔥 动态显示币种名称（不硬编码BTC）
            content.append(f"├─ 预留{base_currency}: ", style="white")
            content.append(
                f"{status_emoji} {current_reserve:.8f}/{reserve_amount:.8f} {base_currency}  ",
                style=health_color
            )
            content.append(f"健康度: {health_percent:.1f}%\n", style=health_color)

            content.append(f"│  └─ 已消耗: ", style="white")
            content.append(
                f"{total_consumed:.8f} {base_currency}  ",
                style="cyan"
            )
            content.append(
                f"交易次数: {reserve_status['trades_count']}  ",
                style="white"
            )
            content.append(
                f"补充次数: {reserve_status['replenish_count']}\n",
                style="white"
            )

        # 🔥 未实现盈亏已删除（重复显示，盈亏统计面板中已有）

        # 🆕 爆仓风险提示（仅作为风险提示，无实质功能）
        liquidation_price, distance_percent, risk_level = self._calculate_liquidation_price(
            stats)

        # 🔥 爆仓风险始终是最后一行
        content.append(f"└─ 爆仓风险: ", style="white")

        if risk_level == 'N/A':
            # 剥头皮模式或无持仓
            content.append("N/A", style="cyan")
        elif liquidation_price is None:
            # 网格范围内安全
            content.append("✅ 安全（网格内不会爆仓）", style="bold green")
        else:
            # 显示爆仓价格和距离
            direction_icon = "⬇️" if stats.current_position > 0 else "⬆️"

            # 根据风险等级设置颜色
            if risk_level == 'safe':
                risk_color = "green"
                risk_icon = "✅"
            elif risk_level == 'warning':
                risk_color = "yellow"
                risk_icon = "⚠️"
            else:  # danger
                risk_color = "red"
                risk_icon = "🚨"

            content.append(
                f"{risk_icon} ${liquidation_price:,.2f} ", style=f"bold {risk_color}")
            content.append(
                f"({direction_icon} {abs(distance_percent):.1f}%)", style=risk_color)

        return Panel(content, title="💰 持仓信息", border_style="yellow")

    def create_pnl_panel(self, stats: GridStatistics) -> Panel:
        """创建盈亏统计面板"""
        # 总盈亏颜色
        total_color = "green" if stats.total_profit > 0 else "red" if stats.total_profit < 0 else "white"
        total_sign = "+" if stats.total_profit >= 0 else ""

        # 已实现盈亏颜色
        realized_color = "green" if stats.realized_profit > 0 else "red" if stats.realized_profit < 0 else "white"
        realized_sign = "+" if stats.realized_profit >= 0 else ""

        # 收益率颜色
        rate_color = "green" if stats.profit_rate > 0 else "red" if stats.profit_rate < 0 else "white"
        rate_sign = "+" if stats.profit_rate >= 0 else ""

        content = Text()
        content.append(f"├─ 已实现: ", style="white")
        content.append(
            f"{realized_sign}${stats.realized_profit:,.2f}             ", style=f"bold {realized_color}")
        content.append(
            f"网格收益: {realized_sign}${stats.realized_profit:,.2f}\n", style=realized_color)

        content.append(f"├─ 未实现: ", style="white")
        content.append(f"{'+' if stats.unrealized_profit >= 0 else ''}${stats.unrealized_profit:,.2f}             ",
                       style="cyan" if stats.unrealized_profit >= 0 else "red")
        content.append(f"手续费: -${stats.total_fees:,.2f}\n", style="red")

        content.append(f"└─ 总盈亏: ", style="white")
        content.append(f"{total_sign}${stats.total_profit:,.2f} ",
                       style=f"bold {total_color}")
        content.append(
            f"({rate_sign}{stats.profit_rate:.2f}%)  ", style=f"bold {rate_color}")
        content.append(
            f"净收益: {total_sign}${stats.net_profit:,.2f}", style=total_color)

        return Panel(content, title="🎯 盈亏统计", border_style="magenta")

    def create_trigger_panel(self, stats: GridStatistics) -> Panel:
        """创建触发统计面板"""
        content = Text()

        content.append(
            f"├─ 买单成交: {stats.filled_buy_count}次               ", style="green")
        content.append(f"卖单成交: {stats.filled_sell_count}次\n", style="red")

        content.append(
            f"├─ 完整循环: {stats.completed_cycles}次 (一买一卖)      ", style="yellow")
        content.append(f"网格利用率: {stats.grid_utilization:.1f}%\n", style="cyan")

        # 平均每次循环收益
        avg_cycle_profit = stats.realized_profit / \
            stats.completed_cycles if stats.completed_cycles > 0 else Decimal(
                '0')
        content.append(f"└─ 平均循环收益: ${avg_cycle_profit:,.2f}",
                       style="green" if avg_cycle_profit > 0 else "white")

        return Panel(content, title="🎯 触发统计", border_style="cyan")

    def create_recent_trades_table(self, stats: GridStatistics) -> Panel:
        """创建最近成交订单表格"""
        table = Table(show_header=True, header_style="bold magenta", box=None)

        table.add_column("时间", style="cyan", width=10)
        table.add_column("类型", width=4)
        table.add_column("价格", style="yellow", width=12)
        table.add_column("数量", style="white", width=12)
        table.add_column("网格层级", style="blue", width=10)

        # 获取最近交易记录
        trades = self.coordinator.tracker.get_trade_history(self.history_limit)

        for trade in reversed(trades[-5:]):  # 只显示最新5条
            time_str = self._format_display_time(trade.get('time'))
            side = trade['side']
            side_style = "green" if side == "buy" else "red"
            price = f"${trade['price']:,.2f}"
            amount = f"{trade['amount']:.5f} {self.base_currency}"
            grid_text = f"Grid {trade['grid_id']}"

            table.add_row(
                time_str,
                f"[{side_style}]{side.upper()}[/{side_style}]",
                price,
                amount,
                grid_text
            )

        if not trades:
            table.add_row("--", "--", "--", "--", "--")

        return Panel(table, title="📈 最近成交订单 (最新5条)", border_style="green")

    def _format_display_time(self, trade_time: Optional[datetime]) -> str:
        """Render recent-trade timestamps in UTC+8."""
        if not isinstance(trade_time, datetime):
            return "--"

        if trade_time.tzinfo is None:
            trade_time = trade_time.replace(tzinfo=timezone.utc)

        return trade_time.astimezone(self.DISPLAY_TIMEZONE).strftime("%H:%M:%S")

    def create_controls_panel(self) -> Panel:
        """创建控制命令面板"""
        content = Text()
        content.append("[P]", style="bold yellow")
        content.append("暂停  ", style="white")
        content.append("[R]", style="bold green")
        content.append("恢复  ", style="white")
        content.append("[S]", style="bold red")
        content.append("停止  ", style="white")
        content.append("[Q]", style="bold cyan")
        content.append("退出", style="white")

        return Panel(content, title="🔧 控制命令", border_style="white")

    def create_orders_panel_display(self, stats: GridStatistics) -> Panel:
        """Alternative orders panel with position-adjusted display counts."""
        content = Text()

        monitoring_mode = getattr(stats, 'monitoring_mode', 'WebSocket')
        if monitoring_mode == "WebSocket":
            mode_icon = "WS"
            mode_style = "bold cyan"
        else:
            mode_icon = "REST"
            mode_style = "bold yellow"

        content.append("監控模式: ", style="white")
        content.append(f"{mode_icon} {monitoring_mode}", style=mode_style)
        content.append("\n")

        buy_grid_ids = []
        sell_grid_ids = []
        if hasattr(self.coordinator, 'state') and hasattr(self.coordinator.state, 'active_orders'):
            for order in self.coordinator.state.active_orders.values():
                grid_id = getattr(order, 'grid_id', None)
                if not grid_id:
                    continue
                if order.side == GridOrderSide.BUY:
                    buy_grid_ids.append(grid_id)
                elif order.side == GridOrderSide.SELL:
                    sell_grid_ids.append(grid_id)

        if buy_grid_ids:
            min_buy = min(buy_grid_ids)
            max_buy = max(buy_grid_ids)
            buy_range = f"Grid {min_buy}-{max_buy}" if min_buy != max_buy else f"Grid {min_buy}"
        else:
            buy_range = "None"

        if sell_grid_ids:
            min_sell = min(sell_grid_ids)
            max_sell = max(sell_grid_ids)
            sell_range = f"Grid {min_sell}-{max_sell}" if min_sell != max_sell else f"Grid {min_sell}"
        else:
            sell_range = "None"

        display_buy_orders, display_sell_orders, position_order_units = self._get_display_pending_order_counts(
            stats
        )

        content.append(f"顯示買單: {display_buy_orders} ({buy_range})\n", style="green")
        content.append(f"顯示賣單: {display_sell_orders} ({sell_range})\n", style="red")

        if position_order_units > 0:
            content.append(
                f"持倉扣除: {position_order_units} 單 ({abs(stats.current_position):.5f} {self.base_currency})\n",
                style="yellow"
            )

        if self.coordinator.config.is_scalping_enabled():
            if self.coordinator.scalping_manager and self.coordinator.scalping_manager.is_active():
                tp_order = self.coordinator.scalping_manager.get_current_take_profit_order()
                if tp_order:
                    content.append("剝頭皮止盈: ", style="white")
                    content.append(
                        f"sell {abs(tp_order.amount):.5f}@${tp_order.price:,.2f} (Grid {tp_order.grid_id})",
                        style="bold yellow"
                    )
                    content.append("\n")
                else:
                    content.append("剝頭皮止盈: 缺少掛單\n", style="red")
            else:
                content.append("剝頭皮止盈: 未啟用\n", style="yellow")

        content.append(f"總掛單數量: {stats.total_pending_orders}", style="white")

        return Panel(content, title="掛單狀態", border_style="blue")

    def create_layout(self, stats: GridStatistics) -> Layout:
        """创建完整布局"""
        layout = Layout()

        layout.split_column(
            Layout(self.create_header(stats), size=3),
            Layout(name="main"),
            Layout(self.create_controls_panel(), size=3)
        )

        layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )

        layout["left"].split_column(
            Layout(self.create_status_panel(stats)),
            Layout(self.create_orders_panel_display(stats)),
            Layout(self.create_trigger_panel(stats))
        )

        layout["right"].split_column(
            Layout(self.create_position_panel(stats)),
            Layout(self.create_pnl_panel(stats)),
            Layout(self.create_recent_trades_table(stats))
        )

        return layout

    async def run(self):
        """运行终端界面"""
        self._running = True

        # ✅ 在 Live 上下文之前打印启动信息
        self.console.print("\n[bold green]✅ 网格交易系统终端界面已启动[/bold green]")
        self.console.print("[cyan]提示: 使用 Ctrl+C 停止系统[/cyan]\n")

        # 短暂延迟，让启动信息显示
        await asyncio.sleep(1)

        # ✅ 清屏，避免之前的输出干扰
        self.console.clear()

        # 🔥 修复：先获取初始统计数据，避免在Live上下文初始化时阻塞
        self.console.print("[cyan]📊 正在获取初始统计数据...[/cyan]")
        try:
            initial_stats = await self.coordinator.get_statistics()
            self.console.print("[green]✅ 初始统计数据获取成功[/green]")
        except Exception as e:
            self.console.print(f"[red]❌ 获取初始统计数据失败: {e}[/red]")
            import traceback
            self.console.print(f"[yellow]{traceback.format_exc()}[/yellow]")
            # 使用空的统计数据作为fallback
            from .models import GridStatistics
            initial_stats = GridStatistics()

        self.console.print("[cyan]🖥️  正在启动Rich终端界面...[/cyan]")

        # 🔥 修复：检查是否使用全屏模式（可通过环境变量控制）
        import os
        use_fullscreen = os.getenv(
            'GRID_UI_FULLSCREEN', 'true').lower() == 'true'
        self.live_console_level = os.getenv(
            'GRID_UI_CONSOLE_LOG_LEVEL', 'WARNING').upper()

        # 🔥 修复：使用try-except捕获Live初始化错误
        try:
            self.console.print(
                f"[yellow]📺 创建Live显示对象（全屏模式: {use_fullscreen}）...[/yellow]")
            live_display = Live(
                self.create_layout(initial_stats),
                refresh_per_second=self.refresh_rate,
                console=self.console,
                screen=use_fullscreen,  # 可配置的全屏模式
                transient=False  # 不使用临时显示
            )
            self.console.print("[green]✅ Live对象创建成功[/green]")
        except Exception as e:
            self.console.print(f"[red]❌ 创建Live对象失败: {e}[/red]")
            import traceback
            self.console.print(f"[yellow]{traceback.format_exc()}[/yellow]")

            # 如果全屏模式失败，尝试非全屏模式
            if use_fullscreen:
                self.console.print("[yellow]⚠️ 尝试使用非全屏模式...[/yellow]")
                try:
                    live_display = Live(
                        self.create_layout(initial_stats),
                        refresh_per_second=self.refresh_rate,
                        console=self.console,
                        screen=False,  # 非全屏模式
                        transient=False
                    )
                    self.console.print("[green]✅ 非全屏模式启动成功[/green]")
                except Exception as e2:
                    self.console.print(f"[red]❌ 非全屏模式也失败: {e2}[/red]")
                    return
            else:
                return

        self.console.print("[cyan]🚀 正在进入Live上下文...[/cyan]")

        # 🔥 添加日志，不使用console.print（因为Live会清除）
        self.logger.info("📺 正在进入Live上下文管理器...")
        console_log_state = set_console_log_level(self.live_console_level)

        try:
            with live_display as live:
                self.logger.info("✅ Rich Live上下文已启动，开始主循环")

                # 🔥 添加一个变量来跟踪是否成功进入主循环
                loop_started = False

                try:
                    while self._running:
                        # 获取最新统计数据
                        try:
                            if not loop_started:
                                self.logger.info("🔄 主循环首次迭代开始...")

                            # 🔥 添加5秒超时保护
                            try:
                                stats = await asyncio.wait_for(
                                    self.coordinator.get_statistics(),
                                    timeout=5.0
                                )
                                if not loop_started:
                                    self.logger.info("✅ 首次统计数据获取成功")
                            except asyncio.TimeoutError:
                                self.logger.error("⏰ 获取统计数据超时（5秒），跳过本次更新")
                                continue

                            # 更新界面
                            live.update(self.create_layout(stats))

                            if not loop_started:
                                self.logger.info("✅ 首次界面更新成功，UI已启动！")
                                loop_started = True
                        except Exception as e:
                            self.logger.error(f"❌ 更新界面失败: {e}")
                            import traceback
                            self.logger.error(f"详细错误: {traceback.format_exc()}")
                            # 继续运行，不要因为单次更新失败而停止

                        # 休眠
                        await asyncio.sleep(1 / self.refresh_rate)

                except KeyboardInterrupt:
                    self.console.print("\n[yellow]收到退出信号...[/yellow]")
                finally:
                    self._running = False
        finally:
            restore_console_log_level(console_log_state)

    def create_recent_trades_table(self, stats: GridStatistics) -> Panel:
        """Create the recent trades panel."""
        table = Table(show_header=True, header_style="bold magenta", box=None)

        table.add_column("Time", style="cyan", width=10)
        table.add_column("Side", width=6)
        table.add_column("Price", style="yellow", width=12)
        table.add_column("Amount", style="white", width=12)
        table.add_column("Grid", style="blue", width=10)

        trades = self.coordinator.tracker.get_trade_history(self.history_limit)

        for trade in reversed(trades[-5:]):
            time_str = self._format_display_time(trade.get('time'))
            side = trade['side']
            side_style = "green" if side == "buy" else "red"
            price = f"${trade['price']:,.2f}"
            amount = f"{trade['amount']:.5f} {self.base_currency}"
            grid_text = f"Grid {trade['grid_id']}"

            table.add_row(
                time_str,
                f"[{side_style}]{side.upper()}[/{side_style}]",
                price,
                amount,
                grid_text
            )

        if not trades:
            table.add_row("--", "--", "--", "--", "--")

        return Panel(table, title="Recent Trades (Last 5)", border_style="green")

    def stop(self):
        """停止终端界面"""
        self._running = False
