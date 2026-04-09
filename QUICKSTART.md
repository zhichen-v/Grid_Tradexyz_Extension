# TradeXYZ 網格交易快速入門

## 1. 環境準備

### 安裝依賴

```bash
pip install -r requirements.txt
```

核心依賴包括 `ccxt`、`aiohttp`、`websockets`、`pyyaml`。

### 目錄結構

```
grid1.3/
├── config/
│   ├── exchanges/
│   │   └── tradexyz_config.yaml    # TradeXYZ 交易所配置
│   └── grid/
│       └── tradexyz_tsla_long.yaml # 網格策略配置（需自行建立）
├── core/adapters/exchanges/adapters/
│   ├── tradexyz.py                 # 主適配器
│   ├── tradexyz_base.py            # 符號映射 & 資產分類
│   ├── tradexyz_rest.py            # REST API
│   └── tradexyz_websocket.py       # WebSocket 即時行情
└── run_grid_trading.py             # 啟動入口
```

---

## 2. 配置交易所認證

編輯 `config/exchanges/tradexyz_config.yaml`，填入你的錢包私鑰和地址：

```yaml
tradexyz:
  authentication:
    private_key: "0xYOUR_PRIVATE_KEY_HERE"
    wallet_address: "0xYOUR_WALLET_ADDRESS_HERE"
```

> **安全提示**：絕對不要將帶有私鑰的配置文件提交到 Git。建議使用環境變數替代：
>
> ```bash
> export TRADEXYZ_API_KEY="0xYOUR_PRIVATE_KEY"
> export TRADEXYZ_API_SECRET="0xYOUR_PRIVATE_KEY"
> export TRADEXYZ_WALLET_ADDRESS="0xYOUR_WALLET_ADDRESS"
> ```

---

## 3. 建立網格策略配置

在 `config/grid/` 下建立你的策略配置文件，例如 `tradexyz_tsla_long.yaml`：

### 範例：TSLA 做多價格移動網格

```yaml
grid_system:
  exchange: "tradexyz"
  symbol: "TSLA"
  grid_type: "follow_long"

  # 價格移動網格參數
  follow_grid_count: 50         # 網格數量
  follow_timeout: 300           # 脫離超時（秒）
  follow_distance: 2            # 脫離距離（格）
  price_offset_grids: 3         # 價格偏移格數

  # 網格參數
  grid_interval: 0.5            # 每格間隔 $0.50
  order_amount: 1               # 每格下單數量
  quantity_precision: 2          # 數量精度（小數位）

  # 手續費
  fee_rate: "0.0001"

  # 健康檢查
  order_health_check_interval: 300
```

### 範例：NVDA 做多固定範圍網格

```yaml
grid_system:
  exchange: "tradexyz"
  symbol: "NVDA"
  grid_type: "long"

  # 固定價格範圍
  price_range:
    lower_price: 100.0
    upper_price: 130.0

  grid_interval: 1.0
  order_amount: 1
  quantity_precision: 2
  fee_rate: "0.0001"
  order_health_check_interval: 300
```

### 範例：加密貨幣 BTC 做多

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
  order_health_check_interval: 300
```

---

## 4. 支援的交易標的

TradeXYZ 同時支援加密貨幣和傳統資產（XYZ 市場），系統會自動判斷並路由到正確的 API。

| 類別 | 標的範例 |
|------|----------|
| **加密貨幣** | `BTC/USDC:USDC`、`ETH/USDC:USDC`、`SOL/USDC:USDC` |
| **美股** | `TSLA`、`AAPL`、`NVDA`、`AMZN`、`MSFT`、`META`、`GOOGL` 等 34 檔 |
| **指數** | `SP500`、`XYZ100` |
| **商品** | `GOLD`、`SILVER`、`WTIOIL`、`BRENTOIL`、`NATGAS` 等 |
| **外匯** | `EUR/USD`、`USD/JPY` |
| **韓股** | `SMSN`、`SKHX`、`HYUNDAI`、`EWY` |

- 加密貨幣符號格式：`BTC/USDC:USDC`（帶後綴）
- XYZ 資產符號格式：直接寫名稱如 `TSLA`、`GOLD`、`SP500`

---

## 5. 啟動

```bash
# 基本啟動
python run_grid_trading.py config/grid/tradexyz_test_follow_long.yaml

# DEBUG 模式（輸出詳細日誌）
python run_grid_trading.py config/grid/tradexyz_test_follow_long.yaml --debug
```

啟動後系統會依序執行：

1. 載入配置
2. 連接交易所（REST + WebSocket）
3. 初始化網格策略、引擎、持倉追蹤器
4. 批量掛單
5. 啟動終端監控介面

按 `Ctrl+C` 或 `Q` 鍵安全退出。

---

## 6. 進階配置

### 保護機制

可在網格配置中啟用四重保護（與其他交易所一致）：

```yaml
  # 剝頭皮模式
  scalping_enabled: true
  scalping_trigger_percent: 15
  scalping_take_profit_grids: 2

  # 本金保護
  capital_protection_enabled: true
  capital_protection_trigger_percent: 40

  # 止盈模式
  take_profit_enabled: true
  take_profit_percentage: 0.005

  # 價格鎖定
  price_lock_enabled: true
  price_lock_threshold: 260.0
```

### 訂閱模式

`tradexyz_config.yaml` 中的 `subscription_mode` 控制 WebSocket 訂閱行為：

- `predefined`：使用預定義的符號列表（預設，適合固定標的）
- `dynamic`：透過 symbol cache service 自動發現標的

```yaml
  subscription_mode:
    mode: predefined
    predefined:
      symbols:
        - BTC/USDC:USDC
        - TSLA
        - AAPL
        - NVDA
      data_types:
        ticker: true
        orderbook: true
        trades: false
        user_data: false
```

---

## 7. 常見問題

**Q: 只想用公開行情，不需要下單？**
不填 `private_key` 即可，系統會以唯讀模式運行。

**Q: 加密貨幣和美股可以同時交易嗎？**
每個網格實例對應一個交易對。如需同時交易多個標的，啟動多個進程即可，每個指定不同的配置文件。

**Q: 日誌在哪裡？**
`logs/` 目錄下，包含 `ExchangeAdapter.log` 和 `system.log`。

**Q: 如何確認連線是否正常？**
啟動時會顯示連線狀態。也可以用 `--debug` 模式查看 WebSocket 訊息和 REST 呼叫細節。
