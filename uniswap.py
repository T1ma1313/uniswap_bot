import time
import threading
from decimal import Decimal, getcontext
from web3 import Web3

from config import NETWORKS, STABLES, WRAPPED_NATIVE, USDC_BY_NETWORK

getcontext().prec = 50

# ----------------- ABIs -----------------

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

ABI_POOL = [
    {
        "name": "slot0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"type": "uint160"}, {"type": "int24"}, {"type": "uint16"}, {"type": "uint16"}, {"type": "uint16"},
            {"type": "uint8"}, {"type": "bool"}
        ]
    },
    {
        "name": "liquidity",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint128"}]
    }
]

ABI_ERC20 = [
    {"name": "symbol", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "string"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint8"}]},
]

ABI_ERC721_ENUM = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"name": "tokenOfOwnerByIndex", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}, {"name": "index", "type": "uint256"}],
     "outputs": [{"type": "uint256"}]},
]

# ----------------- Thread-local cache -----------------

_tls = threading.local()

def _tls_cache():
    if not hasattr(_tls, "cache"):
        _tls.cache = {}
    return _tls.cache


def get_ctx(network_name: str, rpc_url: str):
    """
    Кэшируем w3 + контракты в thread-local, чтобы:
    - не пересоздавать HTTPProvider на каждый вызов
    - безопасно использовать в ThreadPool
    """
    key = (network_name, rpc_url)
    cache = _tls_cache()
    if key in cache:
        return cache[key]

    if network_name not in NETWORKS:
        raise ValueError(f"Unknown network: {network_name}")

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    net = NETWORKS[network_name]
    nfpm = w3.eth.contract(net["nfpm"], abi=ABI_NFPM)
    factory = w3.eth.contract(net["factory"], abi=ABI_FACTORY)

    cache[key] = (w3, nfpm, factory)
    return cache[key]


def call_or(fn, default):
    try:
        return fn()
    except Exception:
        return default


def tick_price(tick: int, dec0: int, dec1: int) -> Decimal:
    return (Decimal("1.0001") ** Decimal(tick)) * (Decimal(10) ** Decimal(dec0 - dec1))


def fmt(x: Decimal) -> str:
    s = f"{x:.2f}"
    whole, frac = s.split(".")
    return f"{int(whole):,}".replace(",", " ") + "," + frac

def _safe_div(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        return Decimal(0)
    return a / b


def _get_erc20_contract(w3, network_name: str, rpc_url: str, token: str):
    cache = _tls_cache()
    key = ("erc20", network_name, rpc_url, Web3.to_checksum_address(token))
    if key in cache:
        return cache[key]

    c = w3.eth.contract(Web3.to_checksum_address(token), abi=ABI_ERC20)
    cache[key] = c
    return c


def _get_pool_contract(w3, network_name: str, rpc_url: str, pool: str):
    cache = _tls_cache()
    key = ("pool", network_name, rpc_url, Web3.to_checksum_address(pool))
    if key in cache:
        return cache[key]

    c = w3.eth.contract(Web3.to_checksum_address(pool), abi=ABI_POOL)
    cache[key] = c
    return c


def _choose_best_weth_usdc_pool(network_name: str, rpc_url: str, w3, factory):
    """
    Ищем лучший референсный WETH/USDC pool по liquidity среди fee tiers.
    """
    cache = _tls_cache()
    key = ("best_weth_usdc_pool", network_name, rpc_url)
    now = time.time()

    cached = cache.get(key)
    if cached and (now - cached["ts"] < 30):
        return cached["pool"], cached["fee"]

    weth = WRAPPED_NATIVE[network_name]
    usdc = USDC_BY_NETWORK[network_name]

    best_pool = None
    best_fee = None
    best_liquidity = -1

    for fee in (100, 500, 3000, 10000):
        try:
            pool = Web3.to_checksum_address(factory.functions.getPool(weth, usdc, fee).call())
            if int(pool, 16) == 0:
                continue

            pool_c = _get_pool_contract(w3, network_name, rpc_url, pool)
            liq = int(call_or(lambda: pool_c.functions.liquidity().call(), 0))

            if liq > best_liquidity:
                best_liquidity = liq
                best_pool = pool
                best_fee = fee
        except Exception:
            continue

    cache[key] = {
        "pool": best_pool,
        "fee": best_fee,
        "ts": now,
    }
    return best_pool, best_fee


def _get_weth_price_usdt(network_name: str, rpc_url: str, w3, factory) -> Decimal | None:
    """
    Возвращает цену 1 WETH в USDT(≈USDC) из лучшего WETH/USDC пула.
    Кэшируем на 30 секунд.
    """
    cache = _tls_cache()
    key = ("weth_price_usdt", network_name, rpc_url)
    now = time.time()

    cached = cache.get(key)
    if cached and (now - cached["ts"] < 30):
        return cached["price"]

    pool, _fee = _choose_best_weth_usdc_pool(network_name, rpc_url, w3, factory)
    if not pool:
        cache[key] = {"price": None, "ts": now}
        return None

    pool_c = _get_pool_contract(w3, network_name, rpc_url, pool)
    tick = int(pool_c.functions.slot0().call()[1])

    weth = WRAPPED_NATIVE[network_name]
    usdc = USDC_BY_NETWORK[network_name]

    # В Uniswap token0/token1 сортируются по адресу
    if int(weth, 16) < int(usdc, 16):
        # token0 = WETH, token1 = USDC
        p = tick_price(tick, 18, 6)  # USDC per WETH
    else:
        # token0 = USDC, token1 = WETH
        p = tick_price(tick, 6, 18)  # WETH per USDC
        p = _safe_div(Decimal(1), p)  # USDC per WETH

    cache[key] = {"price": p, "ts": now}
    return p

def get_amounts(liquidity: int, tick: int, tick_lower: int, tick_upper: int):
    """
    Возвращает raw amounts (без decimals).
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


def get_owner_token_ids(network_name: str, owner: str, rpc_url: str) -> list[int]:
    """
    Список tokenId Uniswap v3 position NFT у owner.
    """
    if network_name not in NETWORKS:
        return []

    w3, _, _ = get_ctx(network_name, rpc_url)
    owner = Web3.to_checksum_address(owner)

    nfpm_enum = w3.eth.contract(NETWORKS[network_name]["nfpm"], abi=ABI_ERC721_ENUM)
    bal = int(nfpm_enum.functions.balanceOf(owner).call())

    token_ids = []
    for i in range(bal):
        token_id = int(nfpm_enum.functions.tokenOfOwnerByIndex(owner, i).call())
        token_ids.append(token_id)

    return token_ids


def is_position_nonzero_and_valid(network_name: str, token_id: int, rpc_url: str) -> bool:
    """
    True если позиция существует и liquidity > 0.
    Быстро: только nfpm.positions().
    """
    if network_name not in NETWORKS:
        return False

    _, nfpm, _ = get_ctx(network_name, rpc_url)
    try:
        pos = nfpm.functions.positions(int(token_id)).call()
        liquidity = int(pos[7])
        return liquidity > 0
    except Exception:
        return False


def get_position_status(network_name: str, token_id: int, rpc_url: str | None = None) -> str:
    """
    Возвращает текст по позиции.
    Поддержка valuation:
    - stable / any
    - WETH / any
    - fallback для any / any без stable и без WETH
    """
    if network_name not in NETWORKS:
        return f"❌ Unknown network: {network_name}"
    if not rpc_url:
        return "❌ RPC URL is not provided"

    w3, nfpm, factory = get_ctx(network_name, rpc_url)

    pos = nfpm.functions.positions(int(token_id)).call()

    token0 = Web3.to_checksum_address(pos[2])
    token1 = Web3.to_checksum_address(pos[3])
    fee = int(pos[4])
    tl = int(pos[5])
    tu = int(pos[6])
    liquidity = int(pos[7])

    t0 = _get_erc20_contract(w3, network_name, rpc_url, token0)
    t1 = _get_erc20_contract(w3, network_name, rpc_url, token1)

    sym0 = call_or(lambda: t0.functions.symbol().call(), "UNK")
    sym1 = call_or(lambda: t1.functions.symbol().call(), "UNK")
    dec0 = int(call_or(lambda: t0.functions.decimals().call(), 18))
    dec1 = int(call_or(lambda: t1.functions.decimals().call(), 18))

    pool = Web3.to_checksum_address(factory.functions.getPool(token0, token1, fee).call())
    if int(pool, 16) == 0:
        return "❌ Pool не найден"

    pool_c = _get_pool_contract(w3, network_name, rpc_url, pool)
    tick = int(pool_c.functions.slot0().call()[1])

    # p_cur = token1 per token0
    p_cur = tick_price(tick, dec0, dec1)
    p_min = tick_price(tl, dec0, dec1)
    p_max = tick_price(tu, dec0, dec1)

    a0_raw, a1_raw = get_amounts(liquidity, tick, tl, tu)
    amount0 = a0_raw / (Decimal(10) ** Decimal(dec0))
    amount1 = a1_raw / (Decimal(10) ** Decimal(dec1))

    is_weth0 = (sym0 == "WETH")
    is_weth1 = (sym1 == "WETH")
    stable0 = (sym0 in STABLES)
    stable1 = (sym1 in STABLES)

    price0_usdt = None
    price1_usdt = None

    # 1) stable / any
    if stable0:
        price0_usdt = Decimal(1)
        price1_usdt = _safe_div(Decimal(1), p_cur)
    elif stable1:
        price0_usdt = p_cur
        price1_usdt = Decimal(1)

    # 2) WETH / any
    elif is_weth0 or is_weth1:
        weth_price_usdt = _get_weth_price_usdt(network_name, rpc_url, w3, factory)

        if weth_price_usdt is not None:
            if is_weth0:
                # p_cur = token1 per WETH
                price0_usdt = weth_price_usdt
                price1_usdt = _safe_div(weth_price_usdt, p_cur)
            else:
                # p_cur = WETH per token0
                price0_usdt = p_cur * weth_price_usdt
                price1_usdt = weth_price_usdt

    owner = nfpm.functions.ownerOf(int(token_id)).call()
    U128_MAX = (1 << 128) - 1

    collect0_raw, collect1_raw = nfpm.functions.collect(
        (int(token_id), owner, U128_MAX, U128_MAX)
    ).call({"from": owner})

    fees0 = Decimal(collect0_raw) / (Decimal(10) ** Decimal(dec0))
    fees1 = Decimal(collect1_raw) / (Decimal(10) ** Decimal(dec1))

    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    pair_price_block = (
        f"💱 Pair {sym0}/{sym1}\n"
        f"min: {fmt(p_min)} {sym1}/{sym0}\n"
        f"max: {fmt(p_max)} {sym1}/{sym0}\n"
        f"cur: {fmt(p_cur)} {sym1}/{sym0}\n\n"
    )

    # Если USDT valuation доступен
    if price0_usdt is not None and price1_usdt is not None:
        value0_usdt = amount0 * price0_usdt
        value1_usdt = amount1 * price1_usdt
        total_value = value0_usdt + value1_usdt

        fees0_usdt = fees0 * price0_usdt
        fees1_usdt = fees1 * price1_usdt
        fees_total_usdt = fees0_usdt + fees1_usdt

        return (
            f"📊 Position {token_id}\n"
            f"{ts}\n\n"
            f"{pair_price_block}"
            f"💧 Position\n"
            f"{sym0}: {amount0:.6f} (~{fmt(value0_usdt)} USDT)\n"
            f"{sym1}: {amount1:.6f} (~{fmt(value1_usdt)} USDT)\n"
            f"TOTAL: {fmt(total_value)} USDT\n\n"
            f"💸 Fees\n"
            f"{sym0}: {fees0:.6f}\n"
            f"{sym1}: {fees1:.6f}\n"
            f"TOTAL: {fmt(fees_total_usdt)} USDT"
        )

    # fallback для any/any без stable и без WETH
    return (
        f"📊 Position {token_id}\n"
        f"{ts}\n\n"
        f"{pair_price_block}"
        f"💧 Position\n"
        f"{sym0}: {amount0:.6f}\n"
        f"{sym1}: {amount1:.6f}\n\n"
        f"💸 Fees\n"
        f"{sym0}: {fees0:.6f}\n"
        f"{sym1}: {fees1:.6f}\n\n"
        f"ℹ️ USDT valuation unavailable for pair {sym0}/{sym1}"
    )