# 網格交易設定檔指南

## 設定檔清單

| 檔案 | 交易所 | 類型 | 說明 |
|------|--------|------|------|
| `backpack_capital_protection_long.yaml` | Backpack | follow_long | 做多完整四重保護範例 |
| `backpack_capital_protection_short.yaml` | Backpack | follow_short | 做空完整四重保護範例 |
| `tradexyz_test_follow_long.yaml` | TradeXYZ | follow_long | NVDA 價格移動網格測試 |
| `tradexyz_test_long.yaml` | TradeXYZ | long | NVDA 固定範圍網格測試 |

---

## 快速啟動

```bash
# 啟動網格交易
uv run python run_grid_trading.py config/grid/<設定檔>.yaml

# DEBUG 模式（詳細 log）
uv run python run_grid_trading.py config/grid/<設定檔>.yaml --debug

# 測試後清理掛單與持倉
uv run python test_tradexyz_cancel_orders.py
```

---

## 網格類型

### 固定範圍網格（`long` / `short`）

在指定的 `lower_price` ~ `upper_price` 區間內佈網格。

- 啟動時只掛**單方向**訂單（做多只掛低於市價的買單，做空只掛高於市價的賣單）
- 高於/低於市價的格子**不會掛單**，避免變成 taker
- 訂單成交後由反手機制自動掛出反方向訂單

```yaml
grid_type: "long"           # 或 "short"
lower_price: 155.0          # 網格下限
upper_price: 195.0          # 網格上限
grid_interval: 5            # 每格間隔（$）
order_amount: 0.2           # 每格數量
```

### 價格移動網格（`follow_long` / `follow_short`）

不指定固定範圍，以當前市價為基準動態計算網格區間，價格移動時自動跟隨重置。

```yaml
grid_type: "follow_long"    # 或 "follow_short"
follow_grid_count: 20       # 網格數量
follow_timeout: 60          # 脫離超時（秒，超過後重置）
follow_distance: 2          # 脫離距離（格數，超出後開始計時）
price_offset_grids: 3       # 價格偏移（讓市價在網格內部，非邊界）
grid_interval: 5.0
order_amount: 0.1
```

### 馬丁格爾網格（`martingale_long` / `martingale_short`）

與固定範圍網格相同，但每格遞增下單數量。

```yaml
grid_type: "martingale_long"
lower_price: 155.0
upper_price: 195.0
grid_interval: 5
order_amount: 0.2           # 第 1 格數量
martingale_increment: 0.1   # 每格遞增量（第 2 格 0.3, 第 3 格 0.4...）
```

---

## 完整參數說明

### 基礎設定

| 參數 | 必填 | 說明 |
|------|------|------|
| `exchange` | Y | 交易所名稱（`tradexyz`, `backpack`, `binance` 等） |
| `symbol` | Y | 交易對（`NVDA`, `BTC`, `HYPE_USDC_PERP` 等） |
| `grid_type` | Y | 網格類型（見上方說明） |
| `grid_interval` | Y | 每格價格間隔（$） |
| `order_amount` | Y | 每格基礎下單數量 |
| `quantity_precision` | Y | 數量小數位數（NVDA=1, BTC=8, ETH=6） |

### 固���範圍網格專用

| 參數 | 說明 |
|------|------|
| `lower_price` | 網格下限價格 |
| `upper_price` | 網格上限價格 |

> 網格數量 = `(upper_price - lower_price) / grid_interval`，自動計算。
>
> 做多網格啟動時，只在**低於市價**的格子掛買單。高於市價的格子留空，等買單成交後由反手機制觸發賣單。做空反之。

### 價格移動網格專用

| 參數 | 預設 | 說明 |
|------|------|------|
| `follow_grid_count` | - | 網格總數 |
| `follow_timeout` | 300 | 脫離超時（秒）：價格離開網格多久後重置 |
| `follow_distance` | 1 | 脫離距離（格數）：離開幾格開始計時 |
| `price_offset_grids` | 0 | 偏移格數：讓市價在網格內部而���邊界 |

### 通用可選參數

| 參數 | 預設 | 說明 |
|------|------|------|
| `martingale_increment` | 0.0 | 馬丁遞增量（僅馬丁模式） |
| `reverse_order_grid_distance` | 1 | 反手掛單距離（格數）：成交後反方向掛幾格外 |
| `order_health_check_interval` | 300 | 訂單健康檢查間隔（秒） |
| `fee_rate` | 0.0001 | 手續費率（用於計算） |

---

## 四重保護系統

四道防線可個別啟用/關閉，觸發優先級為先到先執行。

### 1. 剝頭皮模式（第一道防線）

| 參數 | 預設 | 說明 |
|------|------|------|
| `scalping_enabled` | false | 啟用開關 |
| `scalping_trigger_percent` | 90 | 觸發閾值（%）：買/賣單成交比例 |
| `scalping_take_profit_grids` | 2 | 止盈距離（格數） |

觸發後：取消反方向訂單 → 掛止盈單 → 成交後重置網格。

### 2. 本金保護模式（第二道防線）

| 參數 | 預設 | 說明 |
|------|------|------|
| `capital_protection_enabled` | false | 啟用開關 |
| `capital_protection_trigger_percent` | 40 | 觸發閾值（%）：成交比例更深時觸發 |

觸發後：停止掛單 → 等待抵押品回到初始本金 → 平倉重置。

### 3. 止盈模式（盈利保護）

| 參數 | 預設 | 說明 |
|------|------|------|
| `take_profit_enabled` | false | 啟用開關 |
| `take_profit_percentage` | 0.005 | 止盈閾值（盈利 / 本金比例，0.005 = 0.5%） |

觸發後：平倉所有持倉 → 鎖定利潤 → 重置網格。

### 4. 價格鎖定模式（智能凍結）

| 參數 | 預設 | 說明 |
|------|------|------|
| `price_lock_enabled` | false | 啟用開關 |
| `price_lock_threshold` | - | 鎖定價格閾值（$）：做多時價格向上脫離至此凍結 |
| `price_lock_start_at_threshold` | false | 啟動時若價格已超過閾值，以閾值為起點（僅 follow 模式） |

觸發後：凍結網格（不平倉）→ 保留訂單和持倉 → 價格回歸後自動解除。

---

## 設定範例

### 極簡測試（固定範圍做多，保護全關）

```yaml
grid_system:
  exchange: "tradexyz"
  symbol: "NVDA"
  grid_type: "long"
  lower_price: 155.0
  upper_price: 195.0
  grid_interval: 5
  order_amount: 0.2
  quantity_precision: 1
  martingale_increment: 0.0
  scalping_enabled: false
  capital_protection_enabled: false
  take_profit_enabled: false
  price_lock_enabled: false
  price_lock_threshold: 999999.0
  price_lock_start_at_threshold: false
  reverse_order_grid_distance: 1
  order_health_check_interval: 60
```

### 完整保護（價格移動做��，四重保護全開）

```yaml
grid_system:
  exchange: "tradexyz"
  symbol: "NVDA"
  grid_type: "follow_long"
  follow_grid_count: 200
  follow_timeout: 300
  follow_distance: 2
  price_offset_grids: 5
  grid_interval: 0.5
  order_amount: 0.1
  quantity_precision: 1
  scalping_enabled: true
  scalping_trigger_percent: 90
  scalping_take_profit_grids: 2
  capital_protection_enabled: true
  capital_protection_trigger_percent: 40
  take_profit_enabled: true
  take_profit_percentage: 0.005
  price_lock_enabled: true
  price_lock_threshold: 250.0
  price_lock_start_at_threshold: false
  reverse_order_grid_distance: 1
  order_health_check_interval: 300
```

---

## 注意事項

- 修改設定檔後必須重啟程式才能生效
- 價格移動網格**不需要** `lower_price` / `upper_price`（會自動計算）
- 固定範圍網格**不需要** `follow_*` 參數
- TradeXYZ / Lighter 因 nonce 機制，下單為串行模式（較慢但穩定）
- `price_lock_threshold` 應設在網格範圍之外（做多設在上方，做空設在下方）
- 馬丁模式會快速累積持倉，請謹慎設定 `martingale_increment`
- 測試完畢請執行 `uv run python test_tradexyz_cancel_orders.py` 清理掛單
