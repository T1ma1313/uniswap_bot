# uniswap.py
import time
from decimal import Decimal, getcontext
from web3 import Web3

from config import NETWORKS, STABLES

getcontext().prec = 50

# ===== ABI =====
ABI_FACTORY = [{
    "name": "getPool", "type": "function", "stateMutability": "view",
    "inputs": [
        {"type": "address", "name": "tokenA"},
        {"type": "address", "name": "tokenB"},
        {"type": "uint24", "name": "fee"}
    ],
    "outputs": [{"type": "address", "name": "pool"}]
}]

ABI_NFPM = [
    {"name": "positions", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "uint256", "name": "tokenId"}],
     "outputs": [
         {"type": "uint96"}, {"type": "address"}, {"type": "address"}, {"type": "address"}, {"type": "uint24"},
         {"type": "int24"}, {"type": "int24"}, {"type": "uint128"}, {"type": "uint256"}, {"type": "uint256"},
         {"type": "uint128"}, {"type": "uint128"}
     ]},
    {"name": "ownerOf", "type": "function", "stateMutability": "view",
     "inputs": [{"type": "uint256", "name": "tokenId"}],
     "outputs": [{"type": "address"}]},
    {"name": "collect", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "params", "type": "tuple", "components": [
         {"name": "tokenId", "type": "uint256"},
         {"name": "recipient", "type": "address"},
         {"name": "amount0Max", "type": "uint128"},
         {"name": "amount1Max", "type": "uint128"},
     ]}],
     "outputs": [{"name": "amount0", "type": "uint256"}, {"name": "amount1", "type": "uint256"}]},
]

ABI_POOL = [{
    "name": "slot0", "type": "function", "stateMutability": "view", "inputs": [],
    "outputs": [
        {"type": "uint160"}, {"type": "int24"}, {"type": "uint16"}, {"type": "uint16"}, {"type": "uint16"},
        {"type": "uint8"}, {"type": "bool"}
    ]
}]

ABI_ERC20 = [
    {"name": "symbol", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "string"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint8"}]},
]


# ===== HELPERS =====
def call_or(fn, default):
    try:
        return fn()
    except Exception:
        return default


def tick_price(tick: int, dec0: int, dec1: int) -> Decimal:
    # token1 per token0
    return (Decimal("1.0001") ** Decimal(tick)) * (Decimal(10) ** Decimal(dec0 - dec1))


def fmt(x: Decimal) -> str:
    s = f"{x:.2f}"
    whole, frac = s.split(".")
    return f"{int(whole):,}".replace(",", " ") + "," + frac


def get_amounts(liquidity: int, tick: int, tick_lower: int, tick_upper: int):
    """
    Возвращает raw amounts (в минимальных единицах типа wei, но без учета decimals),
    формулы Uniswap v3. Использует float -> небольшая погрешность возможна.
    """
    L = float(liquidity)

    sp = 1.0001 ** (tick / 2)
    sa = 1.0001 ** (tick_lower / 2)
    sb = 1.0001 ** (tick_upper / 2)

    if tick <= tick_lower:
        amount0 = L * (sb - sa) / (sa * sb)
        amount1 = 0.0
    elif tick < tick_upper:
        amount0 = L * (sb - sp) / (sp * sb)
        amount1 = L * (sp - sa)
    else:
        amount0 = 0.0
        amount1 = L * (sb - sa)

    return Decimal(str(amount0)), Decimal(str(amount1))


# ===== CORE =====
def get_position_status(network_name: str, token_id: int) -> str:
    """
    Возвращает текст ровно в структуре:
    Price (min/max/cur), Position (WETH/USDC/TOTAL), Fees (WETH/USDC/TOTAL).
    Поддерживает пары WETH + (USDC/USDT/DAI). Если другая пара — вернёт ошибку.
    """
    if network_name not in NETWORKS:
        return f"❌ Unknown network: {network_name}"

    net = NETWORKS[network_name]
    w3 = Web3(Web3.HTTPProvider(net["rpc"], request_kwargs={"timeout": 30}))

    nfpm = w3.eth.contract(net["nfpm"], abi=ABI_NFPM)
    factory = w3.eth.contract(net["factory"], abi=ABI_FACTORY)

    pos = nfpm.functions.positions(int(token_id)).call()

    token0 = Web3.to_checksum_address(pos[2])
    token1 = Web3.to_checksum_address(pos[3])
    fee = int(pos[4])
    tl = int(pos[5])
    tu = int(pos[6])
    liquidity = int(pos[7])

    t0 = w3.eth.contract(token0, abi=ABI_ERC20)
    t1 = w3.eth.contract(token1, abi=ABI_ERC20)
    sym0 = call_or(lambda: t0.functions.symbol().call(), "UNK")
    sym1 = call_or(lambda: t1.functions.symbol().call(), "UNK")
    dec0 = int(call_or(lambda: t0.functions.decimals().call(), 18))
    dec1 = int(call_or(lambda: t1.functions.decimals().call(), 18))

    pool = Web3.to_checksum_address(factory.functions.getPool(token0, token1, fee).call())
    if int(pool, 16) == 0:
        return "❌ Pool не найден"

    tick = int(w3.eth.contract(pool, abi=ABI_POOL).functions.slot0().call()[1])

    # prices: token1 per token0
    p_cur = tick_price(tick, dec0, dec1)
    p_min = tick_price(tl, dec0, dec1)
    p_max = tick_price(tu, dec0, dec1)

    # amounts (token units)
    a0_raw, a1_raw = get_amounts(liquidity, tick, tl, tu)
    amount0 = a0_raw / (Decimal(10) ** Decimal(dec0))
    amount1 = a1_raw / (Decimal(10) ** Decimal(dec1))

    # ---- enforce WETH + STABLE ----
    # Want output specifically as WETH + USDC-like stable
    # Determine where WETH is
    is_weth0 = (sym0 == "WETH")
    is_weth1 = (sym1 == "WETH")

    stable0 = (sym0 in STABLES)
    stable1 = (sym1 in STABLES)

    if not ((is_weth0 and stable1) or (is_weth1 and stable0)):
        return f"❌ Сейчас формат вывода поддерживает только WETH + stables ({', '.join(STABLES)}). Пара: {sym0}/{sym1}"

    # Convert prices to "stable per 1 WETH"
    # p_cur is token1 per token0
    if is_weth0 and stable1:
        # token0=WETH, token1=STABLE => p is STABLE per WETH already
        stable_symbol = sym1
        p_weth = p_cur
        p_weth_min = p_min
        p_weth_max = p_max

        weth_amount = amount0
        usdc_amount = amount1  # stable side (may be USDT/DAI etc)
    else:
        # token0=STABLE, token1=WETH => p is WETH per STABLE, invert to STABLE per WETH
        stable_symbol = sym0
        p_weth = Decimal(1) / p_cur
        p_weth_min = Decimal(1) / p_min
        p_weth_max = Decimal(1) / p_max

        weth_amount = amount1
        usdc_amount = amount0  # stable side

    # Value in "USDT" (actually stable ≈ USDT)
    weth_value_usdt = weth_amount * p_weth
    usdc_value_usdt = usdc_amount
    total_value = weth_value_usdt + usdc_value_usdt

    # ---- Fees via collect() simulation ----
    owner = nfpm.functions.ownerOf(int(token_id)).call()
    U128_MAX = (1 << 128) - 1

    collect0_raw, collect1_raw = nfpm.functions.collect(
        (int(token_id), owner, U128_MAX, U128_MAX)
    ).call({"from": owner})

    fees0 = Decimal(collect0_raw) / (Decimal(10) ** Decimal(dec0))
    fees1 = Decimal(collect1_raw) / (Decimal(10) ** Decimal(dec1))

    # fees in terms of WETH + stable
    if is_weth0 and stable1:
        fees_weth = fees0
        fees_usdc = fees1
    else:
        fees_weth = fees1
        fees_usdc = fees0

    fees_weth_usdt = fees_weth * p_weth
    fees_total_usdt = fees_weth_usdt + fees_usdc

    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    # === EXACT STRUCTURE AS YOU REQUESTED ===
    # (Labels remain WETH/USDC, but stable can be USDT/DAI; you can rename later if want.)
    # If you want the stable label to show real symbol, replace "USDC" below with stable_symbol.
    return (
        f"📊 Position {token_id}\n"
        f"{ts}\n\n"
        f"💰 Price\n"
        f"min: {fmt(p_weth_min)}\n"
        f"max: {fmt(p_weth_max)}\n"
        f"cur: {fmt(p_weth)}\n\n"
        f"💧 Position\n"
        f"WETH: {weth_amount:.6f} (~{fmt(weth_value_usdt)} USDT)\n"
        f"USDC: {usdc_amount:.2f} (~{fmt(usdc_value_usdt)} USDT)\n"
        f"TOTAL: {fmt(total_value)} USDT\n\n"
        f"💸 Fees\n"
        f"WETH: {fees_weth:.6f}\n"
        f"USDC: {fees_usdc:.6f}\n"
        f"TOTAL: {fmt(fees_total_usdt)} USDT"
    )