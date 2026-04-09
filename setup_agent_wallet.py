"""
Hyperliquid / TradeXYZ Agent Wallet 授權工具

功能:
  1. 用主錢包私鑰產生並授權一個 Agent Wallet
  2. 將 Agent 私鑰寫入 .env 檔案（主私鑰之後就不需要再用）
  3. 驗證 Agent 可以正常查詢帳戶

Agent Wallet 安全模型:
  - Agent 只能交易，無法提款或轉帳
  - 主錢包私鑰授權完後可以完全離線
  - 如果 Agent 私鑰洩漏，最多只有倉位風險，資金無法被轉走

執行方式:
    uv run python setup_agent_wallet.py

前置條件:
  - 主錢包必須已在 Hyperliquid 存入過資金（帳戶需存在）
  - 主錢包私鑰只在此腳本執行時使用一次
"""

import os
import sys
import yaml
import getpass
from pathlib import Path

import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

BASE_URL = "https://api.hyperliquid.xyz"
CONFIG_PATH = Path("config/exchanges/tradexyz_config.yaml")
ENV_PATH = Path(".env")


# ─── 步驟 1: 取得主錢包私鑰 ────────────────────────────────────────────────

def get_main_credentials():
    """
    取得主錢包私鑰與地址。
    優先讀 config yaml，若為空則要求用戶輸入（不會顯示在畫面上）。
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    auth = cfg["tradexyz"]["authentication"]
    private_key = auth.get("private_key", "").strip()
    wallet_address = auth.get("wallet_address", "").strip()

    if not private_key:
        print("config 中沒有 private_key，請手動輸入（不會顯示）：")
        private_key = getpass.getpass("主錢包私鑰 (0x...): ").strip()

    if not wallet_address:
        wallet_address = input("主錢包地址 (0x...): ").strip()

    return private_key, wallet_address


# ─── 步驟 2: 授權 Agent ────────────────────────────────────────────────────

def authorize_agent(main_private_key: str, wallet_address: str):
    """
    用主錢包授權新的 Agent Wallet，回傳 agent_key 與 agent_address。
    approve_agent() 內部會自動產生新的金鑰對。
    """
    main_account = eth_account.Account.from_key(main_private_key)
    exchange = Exchange(
        main_account,
        BASE_URL,
        account_address=wallet_address,
    )

    print("\n[STEP 2] 向 Hyperliquid 授權 Agent Wallet...")
    result, agent_key = exchange.approve_agent(name="grid_bot")

    print(f"  API 回應: {result}")

    if result.get("status") == "err":
        raise RuntimeError(f"授權失敗: {result.get('response')}")

    agent_account = eth_account.Account.from_key(agent_key)
    print(f"  OK: Agent 已授權")
    print(f"  Agent 地址: {agent_account.address}")

    return agent_key, agent_account.address


# ─── 步驟 3: 儲存 Agent 私鑰到 .env ───────────────────────────────────────

def save_to_env(agent_key: str, agent_address: str, wallet_address: str):
    """
    將 Agent 私鑰寫入 .env，並確保 .env 在 .gitignore 中。
    """
    env_content = f"""# Hyperliquid / TradeXYZ Agent Wallet 設定
# 此檔案由 setup_agent_wallet.py 自動產生，請勿 commit 到 git

# 主錢包地址（公開資訊，無安全疑慮）
HL_WALLET_ADDRESS={wallet_address}

# Agent Wallet 私鑰（可交易，無法提款）
HL_AGENT_KEY={agent_key}

# Agent 錢包地址（公開資訊）
HL_AGENT_ADDRESS={agent_address}
"""
    ENV_PATH.write_text(env_content, encoding="utf-8")
    print(f"\n[STEP 3] Agent 私鑰已儲存到 {ENV_PATH}")

    # 確保 .gitignore 包含 .env
    gitignore = Path(".gitignore")
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".env" not in existing:
        with gitignore.open("a", encoding="utf-8") as f:
            f.write("\n# 環境變數（含 Agent 私鑰）\n.env\n")
        print("  已將 .env 加入 .gitignore")


# ─── 步驟 4: 清除 config 中的明文私鑰 ────────────────────────────────────

def clear_private_key_from_config():
    """
    將 tradexyz_config.yaml 中的 private_key 欄位清空。
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    import re
    # 只清空 private_key 的值，保留 key 本身
    content = re.sub(
        r'(private_key:\s*")[^"]*(")',
        r'\1\2',
        content
    )
    # 也處理不帶引號的情況
    content = re.sub(
        r'(private_key:\s*)0x[0-9a-fA-F]+',
        r'\g<1>""',
        content
    )

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  已清除 {CONFIG_PATH} 中的明文私鑰")


# ─── 步驟 5: 驗證 Agent ────────────────────────────────────────────────────

def verify_agent(wallet_address: str, agent_address: str):
    """
    查詢帳戶上已授權的 Agent 列表，確認授權成功。
    extra_agents API 在部分環境下不支援，失敗時跳過驗證。
    """
    print(f"\n[STEP 5] 驗證帳戶上的 Agent 列表...")
    try:
        info = Info(BASE_URL, skip_ws=True)
        agents = info.extra_agents(wallet_address)
        print(f"  目前授權的 Agents ({len(agents)} 個):")
        for a in agents:
            marker = " ← 剛授權" if a.get("address", "").lower() == agent_address.lower() else ""
            print(f"    名稱: {a.get('name'):15s}  地址: {a.get('address')}{marker}")
        found = any(a.get("address", "").lower() == agent_address.lower() for a in agents)
        if found:
            print("  OK: Agent 驗證成功")
        else:
            print("  WARN: 列表中未找到剛授權的 Agent（可能需要稍等）")
        return found
    except Exception:
        print("  SKIP: extra_agents API 不支援，跳過驗證（授權本身已成功）")
        return True


# ─── 主流程 ────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Hyperliquid Agent Wallet 授權流程")
    print("=" * 60)
    print("""
安全說明:
  - 主錢包私鑰只在此腳本中使用一次，用於簽署授權交易
  - 完成後，私鑰會從 config 清除，改用 Agent 私鑰操作
  - Agent 只能交易，無法提款或轉帳到外部地址
""")

    # 步驟 1: 取得主錢包資訊
    print("[STEP 1] 讀取主錢包資訊...")
    main_private_key, wallet_address = get_main_credentials()
    print(f"  錢包地址: {wallet_address[:10]}...{wallet_address[-6:]}")

    # 步驟 2: 授權 Agent
    try:
        agent_key, agent_address = authorize_agent(main_private_key, wallet_address)
    except RuntimeError as e:
        print(f"\n  FAIL: {e}")
        print("\n  可能原因:")
        print("  - 此錢包尚未在 Hyperliquid 開戶（需先存入資金）")
        print("  - 私鑰不正確")
        sys.exit(1)

    # 步驟 3: 儲存到 .env
    save_to_env(agent_key, agent_address, wallet_address)

    # 步驟 4: 清除 config 中的明文私鑰
    print("\n[STEP 4] 清除 config 中的明文私鑰...")
    clear_private_key_from_config()

    # 步驟 5: 驗證
    verify_agent(wallet_address, agent_address)

    print("\n" + "=" * 60)
    print("  授權完成！")
    print("=" * 60)
    print(f"""
後續使用方式:

  1. 在程式中載入 .env:
       from dotenv import load_dotenv
       load_dotenv()
       agent_key     = os.environ["HL_AGENT_KEY"]
       wallet_address = os.environ["HL_WALLET_ADDRESS"]

  2. 建立 Exchange 客戶端（使用 Agent 金鑰）:
       agent_account = eth_account.Account.from_key(agent_key)
       exchange = Exchange(
           agent_account,
           BASE_URL,
           account_address=wallet_address,  # 主錢包地址
           perp_dexs=["xyz"],
       )

  主錢包私鑰從此不需要出現在任何程式碼中。
""")


if __name__ == "__main__":
    main()
