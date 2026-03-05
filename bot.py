import os
import time
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
from web3 import Web3

from uniswap import (
    get_owner_token_ids,
    is_position_nonzero_and_valid,
    get_position_status,
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set in .env")

ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY")
if not ALCHEMY_API_KEY:
    raise RuntimeError("ALCHEMY_API_KEY is not set in .env")

URL = f"https://api.telegram.org/bot{TOKEN}"
offset = 0

USERS_FILE = "users.json"
POSITIONS_FILE = "positions.json"  # один файл для позиций всех пользователей

pending_wallet = set()  # chat_id ожидающие ввод кошелька
_lock = threading.Lock()

# один Session на весь процесс (быстрее, keep-alive)
HTTP = requests.Session()
HTTP.headers.update({"Connection": "keep-alive"})


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def atomic_save_json(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_users() -> dict:
    return load_json(USERS_FILE, {})


def save_users(users: dict):
    atomic_save_json(USERS_FILE, users)


def load_positions_map() -> dict:
    """
    Формат:
    {
      "chat_id": [ {name, network, token_id}, ... ],
      ...
    }
    """
    data = load_json(POSITIONS_FILE, {})
    if isinstance(data, list):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_positions_map(data: dict):
    atomic_save_json(POSITIONS_FILE, data)


def send(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    # Telegram иногда медлит — таймауты оставим разумные
    HTTP.post(URL + "/sendMessage", json=payload, timeout=20)


def updates():
    global offset
    r = HTTP.get(
        URL + "/getUpdates",
        params={"timeout": 30, "offset": offset},
        timeout=35
    )
    return r.json()


def build_rpc(network: str) -> str:
    prefixes = {
        "eth": "https://eth-mainnet.g.alchemy.com/v2/",
        "base": "https://base-mainnet.g.alchemy.com/v2/",
        "arbitrum": "https://arb-mainnet.g.alchemy.com/v2/",
    }
    if network not in prefixes:
        raise ValueError(f"Unknown network: {network}")
    return prefixes[network] + ALCHEMY_API_KEY.strip()


def is_valid_wallet(addr: str) -> bool:
    return Web3.is_address((addr or "").strip())


def normalize_wallet(addr: str) -> str:
    return Web3.to_checksum_address(addr.strip())


def ensure_user(users: dict, chat_id: int) -> dict:
    key = str(chat_id)
    if key not in users:
        users[key] = {"created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    return users[key]


def _discover_network_positions(net: str, wallet: str, rpc: str, existing_set: set[tuple[str, int]]):
    """
    Возвращает список новых позиций для сети net (только liquidity > 0),
    плюс статистику scanned/skipped.
    """
    new_positions = []
    scanned = 0
    skipped = 0

    token_ids = get_owner_token_ids(net, wallet, rpc_url=rpc)

    # Параллелим проверки tokenId -> liquidity > 0 (это main bottleneck)
    # Ограничиваем воркеров, чтобы не DDoS-нуть RPC
    max_workers = min(16, max(4, (os.cpu_count() or 4)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {}
        for tid in token_ids:
            scanned += 1
            tid_int = int(tid)
            key = (net, tid_int)
            if key in existing_set:
                skipped += 1
                continue
            fut = ex.submit(is_position_nonzero_and_valid, net, tid_int, rpc_url=rpc)
            fut_map[fut] = tid_int

        for fut in as_completed(fut_map):
            tid_int = fut_map[fut]
            try:
                ok = fut.result()
            except Exception:
                ok = False
            if not ok:
                skipped += 1
                continue
            existing_set.add((net, tid_int))
            new_positions.append({
                "name": f"Position {tid_int}",
                "network": net,
                "token_id": tid_int,
            })

    return new_positions, scanned, skipped


def _calc_status_for_position(p: dict, rpc_url: str):
    # отдельная функция, чтобы удобнее параллелить
    return get_position_status(p["network"], int(p["token_id"]), rpc_url=rpc_url)


def main():
    global offset
    print("Bot started...")

    users = load_users()
    positions_map = load_positions_map()

    keyboard_main = {
        "keyboard": [
            [{"text": "/status"}, {"text": "/discover"}],
            [{"text": "/wallet"}, {"text": "/setwallet"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

    while True:
        try:
            data = updates()

            for u in data.get("result", []):
                offset = u["update_id"] + 1

                msg = u.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                chat_id_str = str(chat_id)
                text = (msg.get("text") or "").strip()

                # ---- waiting for wallet ----
                if chat_id in pending_wallet and not text.startswith("/"):
                    if not is_valid_wallet(text):
                        send(chat_id, "❌ Это не похоже на wallet address. Пришли адрес вида 0x... ещё раз.")
                        continue

                    wallet = normalize_wallet(text)

                    with _lock:
                        udata = ensure_user(users, chat_id)
                        udata["wallet"] = wallet
                        save_users(users)

                    pending_wallet.remove(chat_id)
                    send(chat_id, f"✅ Кошелёк сохранён: {wallet}\nТеперь нажми /discover.", reply_markup=keyboard_main)
                    continue

                # ---- commands ----
                if text == "/start":
                    udata = users.get(chat_id_str, {})
                    wallet = udata.get("wallet")
                    if wallet:
                        send(chat_id, f"Ты уже зарегистрирован ✅\nWallet: {wallet}\nЖми /discover или /status.", reply_markup=keyboard_main)
                    else:
                        pending_wallet.add(chat_id)
                        send(chat_id, "Привет! Пришли свой wallet address (0x...), чтобы я нашёл твои Uniswap позиции.")
                    continue

                if text == "/setwallet":
                    pending_wallet.add(chat_id)
                    send(chat_id, "Ок. Пришли новый wallet address (0x...) одним сообщением.")
                    continue

                if text == "/wallet":
                    udata = users.get(chat_id_str, {})
                    wallet = udata.get("wallet")
                    send(chat_id, f"Твой wallet: {wallet}" if wallet else "Кошелёк ещё не задан. Напиши /setwallet")
                    continue

                if text == "/discover":
                    udata = users.get(chat_id_str, {})
                    wallet = udata.get("wallet")
                    if not wallet:
                        pending_wallet.add(chat_id)
                        send(chat_id, "Сначала пришли wallet address (0x...) — отправь его следующим сообщением.")
                        continue

                    send(chat_id, "🔎 Ищу активные позиции (liquidity > 0)...")

                    with _lock:
                        positions_map.setdefault(chat_id_str, [])
                        existing = {(p["network"], int(p["token_id"])) for p in positions_map[chat_id_str]}

                    added_total = 0
                    scanned_total = 0
                    skipped_total = 0

                    for net in ("eth", "base", "arbitrum"):
                        try:
                            rpc = build_rpc(net)
                            new_pos, scanned, skipped = _discover_network_positions(net, wallet, rpc, existing)
                            scanned_total += scanned
                            skipped_total += skipped

                            if new_pos:
                                with _lock:
                                    positions_map[chat_id_str].extend(new_pos)

                                added_total += len(new_pos)

                        except Exception as e:
                            send(chat_id, f"⚠️ {net}: не смог получить позиции ({e})")

                    with _lock:
                        save_positions_map(positions_map)

                    if added_total == 0:
                        send(
                            chat_id,
                            f"✅ Готово. Новых активных позиций не найдено.\n"
                            f"Проверено: {scanned_total}, пропущено: {skipped_total}\nЖми /status.",
                            reply_markup=keyboard_main
                        )
                    else:
                        send(
                            chat_id,
                            f"✅ Готово. Добавлено новых активных позиций: {added_total}\n"
                            f"Проверено: {scanned_total}, пропущено: {skipped_total}\nЖми /status.",
                            reply_markup=keyboard_main
                        )
                    continue

                if text == "/status":
                    udata = users.get(chat_id_str, {})
                    wallet = udata.get("wallet")
                    if not wallet:
                        pending_wallet.add(chat_id)
                        send(chat_id, "Сначала пришли wallet address (0x...) — отправь его следующим сообщением.")
                        continue

                    user_positions = positions_map.get(chat_id_str, [])
                    if not user_positions:
                        send(chat_id, "У тебя пока нет позиций. Нажми /discover, чтобы найти их автоматически.")
                        continue

                    send(chat_id, f"⏳ Считаю {len(user_positions)} позиции...")

                    # Параллелим вычисления, но отправку сообщений делаем последовательно (чтобы не словить лимиты Telegram)
                    tasks = []
                    for i, p in enumerate(user_positions, start=1):
                        rpc_url = build_rpc(p["network"])
                        tasks.append((i, p, rpc_url))

                    max_workers = min(12, max(4, (os.cpu_count() or 4)))
                    results = {}

                    with ThreadPoolExecutor(max_workers=max_workers) as ex:
                        fut_map = {
                            ex.submit(_calc_status_for_position, p, rpc_url): (i, p, rpc_url)
                            for (i, p, rpc_url) in tasks
                        }
                        for fut in as_completed(fut_map):
                            i, p, _ = fut_map[fut]
                            try:
                                results[i] = fut.result()
                            except Exception as e:
                                results[i] = f"❌ ERROR: {e}"

                    # Отправляем в правильном порядке
                    for i, p, _ in tasks:
                        header = f"🔹 {i}) {p.get('name','Position')} | {p['network']} | tokenId={p['token_id']}\n\n"
                        send(chat_id, header + results.get(i, "❌ ERROR: empty result"))
                        time.sleep(0.15)  # небольшой лимит на отправку

                    continue

                if text == "/help":
                    send(chat_id, "Команды:\n/start\n/setwallet\n/wallet\n/discover\n/status", reply_markup=keyboard_main)
                    continue

                if text and not text.startswith("/"):
                    send(chat_id, "Не понял. Напиши /help")

        except Exception as e:
            print("ERROR:", e)

        time.sleep(0.6)


if __name__ == "__main__":
    main()