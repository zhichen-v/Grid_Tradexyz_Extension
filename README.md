# TradeXYZ 網格交易系統

基於 Hyperliquid API 的多資產網格交易系統，支援加密貨幣永續合約與 XYZ 市場（美股、指數、商品、外匯）。

---

## 快速指令

```bash
# 所有 Python 指令透過 uv
uv run python run_grid_trading.py config/grid/<config>.yaml
uv run python run_grid_trading.py config/grid/<config>.yaml --debug

# 測試後清理掛單與持倉（每次測試完必須執行）
uv run python test_tradexyz_cancel_orders.py

# Agent Wallet 首次設定
uv run python setup_agent_wallet.py
```

---

## TradeXYZ 架構

TradeXYZ 基於 Hyperliquid API，透過 `dex="xyz"` 命名空間支援傳統金融資產，並與加密貨幣路徑**完全分離**。

### 雙路徑下單機制

| 功能 | 加密貨幣（BTC、ETH…） | XYZ 市場（NVDA、TSLA…） |
|------|----------------------|------------------------|
| 行情查詢 | ccxt `fetch_ticker` | HTTP POST `dex="xyz"` |
| 訂單簿 | ccxt `fetch_order_book` | HTTP POST `dex="xyz"` |
| 持倉查詢 | ccxt `fetch_positions` | HTTP POST `dex="xyz"` |
| **下單 / 取消** | **ccxt** | **hyperliquid-python-sdk**（`perp_dexs=["xyz"]`） |
| **查詢掛單** | **ccxt** | HTTP POST `frontendOpenOrders` |

> ccxt 不支援 XYZ 市場符號，XYZ 下單必須走 `hyperliquid-python-sdk`。

### 模組結構

```
core/adapters/exchanges/adapters/
├── tradexyz.py           # 主 Adapter（組合 base / rest / websocket）
├── tradexyz_base.py      # 符號辨識 / 映射，XYZ 資產清單
├── tradexyz_rest.py      # REST API（ccxt + SDK 雙路徑）
└── tradexyz_websocket.py # WebSocket 即時行情
```

`TradeXYZAdapter` 組合三個子元件，對外暴露與其他交易所一致的介面：

```
TradeXYZAdapter
├── TradeXYZBase    ← 符號辨識、映射工具
├── TradeXYZRest    ← 所有 REST 操作（行情 / 下單 / 取消 / 查詢）
└── TradeXYZWebSocket ← 行情訂閱
```

---

## 支援的交易標的

系統會自動依符號判斷走哪條路徑，無需手動指定。

| 類別 | 符號範例 | 格式 |
|------|----------|------|
| 加密貨幣 | BTC、ETH、SOL | `BTC/USDC:USDC` |
| 美股（34 檔） | TSLA、NVDA、AAPL、AMZN、META、MSFT… | `TSLA` |
| 指數 | SP500、XYZ100 | `SP500` |
| 商品 | GOLD、SILVER、WTIOIL、BRENTOIL、NATGAS… | `GOLD` |
| 外匯 | EUR/USD、USD/JPY | `EUR/USD` |
| 韓股 | SMSN、SKHX、HYUNDAI、EWY | `SMSN` |

完整的美股清單定義在 `tradexyz_base.py` 的 `XYZ_ASSET_CLASSES`。

### 符號辨識邏輯（`tradexyz_base.py`）

```python
def is_xyz_symbol(self, symbol: str) -> bool:
    if symbol.startswith("xyz:"):      # xyz: 前綴 → XYZ
        return True
    base = self._extract_base_symbol(symbol)
    for assets in self.XYZ_ASSET_CLASSES.values():
        if base in assets:             # 在清單內 → XYZ
            return True
    return False                       # 其餘 → 加密貨幣
```

---

## 環境設定

### 依賴安裝

```bash
# 透過 uv（推薦）
uv pip install -r requirements.txt

# 核心套件
# ccxt                  加密貨幣統一 API
# hyperliquid-python-sdk XYZ 市場下單
# aiohttp               非同步 HTTP（XYZ 行情查詢）
# websockets            WebSocket 數據流
# pyyaml / rich / eth_account
```

### 認證設定

**推薦：Agent Wallet（只有交易權限，無法提款）**

```bash
# 首次設定，需要主錢包私鑰
uv run python setup_agent_wallet.py
```

設定完成後，`.env` 會自動產生：

```
HL_WALLET_ADDRESS=0x主錢包地址
HL_AGENT_KEY=0xAgent私鑰
HL_AGENT_ADDRESS=0xAgent地址
```

**備用：config 檔案**

```yaml
# config/exchanges/tradexyz_config.yaml
tradexyz:
  authentication:
    private_key: "0xYOUR_PRIVATE_KEY"
    wallet_address: "0xYOUR_WALLET_ADDRESS"
```

> 含私鑰的設定檔已加入 `.gitignore`，禁止 commit。

**認證優先級**

1. 環境變數 `TRADEXYZ_API_KEY` / `TRADEXYZ_WALLET_ADDRESS`
2. `.env` 中的 `HL_AGENT_KEY` / `HL_WALLET_ADDRESS`（自動載入）
3. `config/exchanges/tradexyz_config.yaml`

---

## 網格設定

### 快速範例

**XYZ 市場（NVDA 價格移動網格）**

```yaml
grid_system:
  exchange: "tradexyz"
  symbol: "NVDA"
  grid_type: "follow_long"

  follow_grid_count: 20
  follow_timeout: 60
  follow_distance: 2
  price_offset_grids: 3

  grid_interval: 1.0
  order_amount: 0.1
  quantity_precision: 1
  fee_rate: "0.0001"
  order_health_check_interval: 300
```

**XYZ 市場（NVDA 固定範圍網格）**

```yaml
grid_system:
  exchange: "tradexyz"
  symbol: "NVDA"
  grid_type: "long"

  lower_price: 100.0
  upper_price: 130.0
  grid_interval: 1.0
  order_amount: 0.1
  quantity_precision: 1
  fee_rate: "0.0001"
```

**加密貨幣（BTC 價格移動網格）**

```yaml
grid_system:
  exchange: "tradexyz"
  symbol: "BTC/USDC:USDC"
  grid_type: "follow_long"

  follow_grid_count: 100
  follow_timeout: 300
  follow_distance: 2
  price_offset_grids: 5

  grid_interval: 50
  order_amount: 0.001
  quantity_precision: 5
  fee_rate: "0.0001"
```

### 網格類型

| grid_type | 說明 |
|-----------|------|
| `long` / `short` | 固定範圍網格（指定 lower/upper price） |
| `follow_long` / `follow_short` | 價格移動網格（動態跟隨，無需指定範圍） |
| `martingale_long` / `martingale_short` | 馬丁格爾（每格遞增數量） |

固定範圍網格啟動時只掛單方向訂單（做多只掛低於市價的買單），避免 taker 成交。

### 核心參數

| 參數 | 必填 | 說明 |
|------|------|------|
| `exchange` | Y | `"tradexyz"` |
| `symbol` | Y | 交易標的（見上方格式） |
| `grid_type` | Y | 網格類型 |
| `grid_interval` | Y | 每格價格間隔（$） |
| `order_amount` | Y | 每格基礎下單數量 |
| `quantity_precision` | Y | 數量小數位（NVDA=1、BTC=8、GOLD=4） |
| `lower_price` | 固定範圍 | 網格下限 |
| `upper_price` | 固定範圍 | 網格上限 |
| `follow_grid_count` | 移動網格 | 網格總數 |
| `follow_timeout` | 移動網格 | 脫離超時秒數 |
| `follow_distance` | 移動網格 | 脫離距離（格數） |
| `price_offset_grids` | 移動網格 | 讓市價在網格內部的偏移格數 |

---

## XYZ 市場注意事項

### 價格精度（5 位有效數字限制）

Hyperliquid API 要求價格最多 5 位有效數字，超過會收到 `tick size` 錯誤：

```
100.685  → 6 位有效數字 → 被拒絕
100.68   → 5 位有效數字 → 通過
```

`tradexyz_rest.py` 的 `_round_to_sig_figs()` 會自動處理，無需手動調整。

### 串行下單（Nonce 機制）

TradeXYZ（與 Lighter 相同）因 nonce 衝突問題，`grid_engine_impl.py` 已強制設為串行下單模式，不可用 `asyncio.gather` 併發。這是正確行為，下單速度稍慢但穩定。

### 數量精度參考

| 標的 | `quantity_precision` |
|------|---------------------|
| NVDA | 1 |
| TSLA | 1 |
| GOLD | 4 |
| SP500 | 1 |
| BTC | 8 |

---

## 四重保護系統

可在網格設定中個別啟用，觸發優先級為先到先執行。

### 剝頭皮（第一道防線）

```yaml
scalping_enabled: true
scalping_trigger_percent: 15   # 買/賣單成交 15% 後觸發
scalping_take_profit_grids: 2  # 掛出 2 格外的止盈單
```

觸發：取消反方向訂單 → 掛止盈單 → 成交後重置。

### 本金保護（第二道防線）

```yaml
capital_protection_enabled: true
capital_protection_trigger_percent: 40  # 成交更深時觸發
```

觸發：停止掛單 → 等待抵押品回到初始本金 → 平倉重置。

### 止盈模式

```yaml
take_profit_enabled: true
take_profit_percentage: 0.005  # 盈利超過本金 0.5% 觸發
```

觸發：平倉所有持倉 → 鎖定利潤 → 重置網格。

### 價格鎖定

```yaml
price_lock_enabled: true
price_lock_threshold: 260.0           # 做多時向上脫離至此凍結
price_lock_start_at_threshold: false  # 啟動時若已超過閾值，以閾值為起點
```

觸發：凍結網格（不平倉）→ 保留訂單 → 價格回歸後自動解除。

---

## WebSocket 訂閱設定

`config/exchanges/tradexyz_config.yaml` 中的 `subscription_mode` 控制訂閱行為：

```yaml
tradexyz:
  subscription_mode:
    mode: predefined          # predefined（固定清單）或 dynamic（自動發現）
    predefined:
      symbols:
        - BTC/USDC:USDC
        - NVDA
        - TSLA
        - GOLD
      data_types:
        ticker: true
        orderbook: true
        trades: false
        user_data: false
```

---

## 啟動流程

```bash
uv run python run_grid_trading.py config/grid/tradexyz_test_follow_long.yaml
uv run python run_grid_trading.py config/grid/tradexyz_test_follow_long.yaml --debug
```

啟動順序：

1. 讀取 yaml 設定
2. 連接交易所（REST + WebSocket）
3. 初始化策略、引擎、持倉追蹤器
4. 批量掛單（串行）
5. 啟動終端監控介面

按 `Ctrl+C` 或 `Q` 安全退出。

---

## 現有設定檔

位置：`config/grid/`

| 檔案 | 類型 | 說明 |
|------|------|------|
| `tradexyz_test_follow_long.yaml` | follow_long | NVDA 價格移動網格測試 |
| `tradexyz_test_long.yaml` | long | NVDA 固定範圍網格測試 |
| `tradexyz_long.yaml` | long | 正式做多設定 |
| `backpack_capital_protection_long.yaml` | follow_long | Backpack 完整四重保護範例 |

---

## 常見問題

**Q: 不需要下單，只想看行情？**
不填 `private_key` 即可，系統以唯讀模式運行。

**Q: 加密貨幣和美股可以同時交易嗎？**
每個進程對應一個設定檔。同時交易多標的需啟動多個進程，各指定不同設定檔。

**Q: 日誌在哪裡？**
`logs/` 目錄下，按模組分檔。`--debug` 可看 WebSocket 訊息和 REST 呼叫細節。

**Q: 測試完如何清理？**
```bash
uv run python test_tradexyz_cancel_orders.py
```

**Q: 遇到 `tick size` 錯誤？**
XYZ 市場價格超過 5 位有效數字。`tradexyz_rest.py` 已自動處理，若仍出現請確認使用最新版本。

**Q: 遇到 `duplicate nonce` 錯誤？**
確認 `grid_engine_impl.py` 將 tradexyz 設為串行模式（非 `asyncio.gather`）。

---

## 開發注意事項

- 所有腳本用 `uv run python <script>` 執行
- Windows 終端加 `PYTHONIOENCODING=utf-8` 避免 emoji 編碼錯誤
- `Adapter.create_order()` 簽名須包含 `batch_mode: bool = False`
- Lighter 和 TradeXYZ 因 nonce 機制必須串行下單
- 固定範圍網格啟動時只掛單方向訂單，避免 taker 成交
- **測試後務必執行清理腳本**

---

## 致謝

本專案基於 [cryptocj520/grid1.3](https://github.com/cryptocj520/grid1.3) 框架開發。
