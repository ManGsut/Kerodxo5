import os
import asyncio
import base64
import socket
from urllib.parse import urlparse
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
import uvicorn
import httpx

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

BOT_TOKEN = os.getenv("BOT_TOKEN", "8851917192:AAGtTPzxO05av2_0WoeNbz9qJSPgIvwLQ9Y")

# Временное хранилище в памяти
ACTIVE_NODES = []
USER_DRAFTS = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ПАРСЕР И ПРОВЕРКА СОЕДИНЕНИЯ ---
async def parse_and_check(sub_url: str):
    headers = {"User-Agent": "Happ/3.2.0 (Android 14; SM-A546B)"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            res = await client.get(sub_url, headers=headers)
            raw = res.text.strip()
    except Exception:
        return []

    try:
        decoded = base64.b64decode(raw).decode('utf-8', errors='ignore')
    except Exception:
        decoded = raw

    configs = [line.strip() for line in decoded.splitlines() if line.startswith(("vless://", "vmess://", "ss://", "trojan://"))]
    valid_nodes = []

    for cfg in configs:
        try:
            parsed = urlparse(cfg)
            host = parsed.hostname
            port = parsed.port or 443
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.5)
            if s.connect_ex((host, port)) == 0:
                name = parsed.fragment if parsed.fragment else "Сервер сети"
                valid_nodes.append({"raw": cfg, "name": name})
            s.close()
        except Exception:
            continue

    return valid_nodes

# --- КЛАВИАТУРЫ МЕНЮ ---
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить VPN-подписку", callback_data="btn_add")],
        [InlineKeyboardButton(text="🔗 Моя ссылка на сеть", callback_data="btn_link")],
        [InlineKeyboardButton(text="🌍 Список серверов сети", callback_data="btn_list")],
        [InlineKeyboardButton(text="📱 Как настроить (Happ)", callback_data="btn_help")]
    ])

# --- ОБРАБОТЧИКИ TELEGRAM ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "🌐 **SHARESUB NETWORK**\n"
        "Делись VPN. Собирай общую сеть.\n\n"
        "Добро пожаловать в единую систему обмена VPN-узлами.\n"
        f"├ 🌍 Активных серверов: **{len(ACTIVE_NODES)}**\n"
        "└ ⚡️ Статус: **Онлайн**\n\n"
        "Выберите действие ниже:"
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "btn_add")
async def cb_add(call: CallbackQuery):
    await call.message.edit_text(
        "📥 **Отправьте мне ссылку на вашу VPN-подписку** прямым сообщением в этот чат.\n\n"
        "Бот проверит доступность узлов и добавит их в общий пул.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ В главное меню", callback_data="btn_back")]
        ]),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "btn_back")
async def cb_back(call: CallbackQuery):
    await cmd_start(call.message)

@dp.callback_query(F.data == "btn_link")
async def cb_link(call: CallbackQuery):
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost:8000")
    link = f"https://{host}/sub" if "render.com" in host else f"http://{host}/sub"
    await call.message.edit_text(
        f"🔗 **Ваша единая ссылка на подписку:**\n\n`{link}`\n\n"
        f"В ней собрано **{len(ACTIVE_NODES)}** серверов сети.\n"
        "Скопируйте её и вставьте в клиент **Happ** или **v2rayNG**.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ В главное меню", callback_data="btn_back")]
        ]),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "btn_list")
async def cb_list(call: CallbackQuery):
    if not ACTIVE_NODES:
        text = "📭 В сети пока нет активных серверов. Добавьте первый!"
    else:
        text = f"🌍 **Список активных узлов ({len(ACTIVE_NODES)} шт.):**\n\n"
        for i, node in enumerate(ACTIVE_NODES[:15], 1):
            text += f"{i}. 🟢 {node.get('name', 'Сервер')}\n"
        if len(ACTIVE_NODES) > 15:
            text += f"\n...и ещё {len(ACTIVE_NODES) - 15} локаций."
            
    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ В главное меню", callback_data="btn_back")]
        ]),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "btn_help")
async def cb_help(call: CallbackQuery):
    await call.message.edit_text(
        "📱 **Инструкция по подключению:**\n\n"
        "1. Установите приложение **Happ** из Google Play / App Store.\n"
        "2. Нажмите в боте «🔗 Моя ссылка на сеть» и скопируйте URL.\n"
        "3. Откройте Happ ➔ нажмите плюс в углу ➔ выберите «Добавить подписку».\n"
        "4. Вставьте ссылку и обновите конфигурации.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ В главное меню", callback_data="btn_back")]
        ]),
        parse_mode="Markdown"
    )

@dp.message(F.text.startswith("http"))
async def handle_sub_link(message: Message):
    wait_msg = await message.answer(
        "🌐 **Импорт VPN-подписки...**\n"
        "⏳ Генерация виртуального устройства и проверка нод Xray...",
        parse_mode="Markdown"
    )
    
    nodes = await parse_and_check(message.text.strip())
    
    if not nodes:
        await wait_msg.edit_text(
            "❌ Не удалось получить серверы по этой ссылке, либо они сейчас недоступны.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Назад", callback_data="btn_back")]
            ])
        )
        return

    USER_DRAFTS[message.chat.id] = nodes
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🟢 Добавить все ({len(nodes)} шт.)", callback_data="confirm_add")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="btn_back")]
    ])
    
    await wait_msg.edit_text(
        f"✅ Найдено рабочих серверов: **{len(nodes)}**\n\n"
        "Добавить их в общий каталог сети ShareSub?",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "confirm_add")
async def cb_confirm(call: CallbackQuery):
    user_id = call.message.chat.id
    nodes = USER_DRAFTS.get(user_id, [])
    
    added_count = 0
    existing_raws = {n["raw"] for n in ACTIVE_NODES}
    for n in nodes:
        if n["raw"] not in existing_raws:
            ACTIVE_NODES.append(n)
            added_count += 1
            
    await call.message.edit_text(
        f"🎉 **Серверы успешно импортированы!**\n\n"
        f"Добавлено новых узлов: **{added_count}**\n"
        f"Всего доступно в сети: **{len(ACTIVE_NODES)}**\n\n"
        "Используйте кнопку «Моя ссылка на сеть» в меню, чтобы загрузить их в клиент.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="btn_back")]
        ]),
        parse_mode="Markdown"
    )

# --- ВЕБ-СЕРВЕР (FASTAPI) ДЛЯ HAPP И БРАУЗЕРА ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(dp.start_polling(bot))
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.get("/sub")
async def route_sub(request: Request):
    ua = request.headers.get("user-agent", "").lower()
    
    # Отдача чистого конфига для Happ/v2rayNG/Streisand
    if any(app_name in ua for app_name in ["happ", "v2ray", "nekobox", "sing-box", "streisand", "clash"]):
        lines = [n["raw"] for n in ACTIVE_NODES]
        payload = "\n".join(lines)
        return PlainTextResponse(base64.b64encode(payload.encode()).decode())

    # Красивая страница в тёмной теме для браузера
    html_page = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ShareSub Network</title>
        <style>
            body {{
                background-color: #0b0f19;
                color: #f8fafc;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 30px 15px;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            .card {{
                background: #131c2e;
                border: 1px solid #1e293b;
                border-radius: 18px;
                padding: 24px;
                max-width: 420px;
                width: 100%;
                box-shadow: 0 10px 25px rgba(0,0,0,0.5);
                box-sizing: border-box;
            }}
            .badge {{
                display: inline-block;
                background: rgba(34, 197, 94, 0.15);
                color: #4ade80;
                padding: 6px 12px;
                border-radius: 99px;
                font-size: 13px;
                font-weight: 600;
                margin-bottom: 12px;
            }}
            h2 {{ margin: 0 0 8px 0; font-size: 22px; }}
            p {{ color: #94a3b8; font-size: 14px; line-height: 1.5; }}
            .stats {{
                display: flex;
                justify-content: space-between;
                margin: 20px 0;
                background: #0b0f19;
                padding: 14px;
                border-radius: 12px;
            }}
            .stat-item {{ text-align: center; }}
            .stat-val {{ font-weight: bold; font-size: 18px; color: #38bdf8; }}
            .stat-lbl {{ font-size: 11px; color: #64748b; margin-top: 4px; }}
            .btn {{
                display: block;
                background: #2563eb;
                color: white;
                text-decoration: none;
                text-align: center;
                padding: 14px;
                border-radius: 12px;
                font-weight: 600;
                font-size: 15px;
                margin-top: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="badge">● LIVE NETWORK</div>
            <h2>ShareSub Network</h2>
            <p>Единый шлюз распределения VPN-узлов сообщества.</p>
            
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-val">{len(ACTIVE_NODES)}</div>
                    <div class="stat-lbl">СЕРВЕРОВ</div>
                </div>
                <div class="stat-item">
                    <div class="stat-val">Онлайн</div>
                    <div class="stat-lbl">СТАТУС</div>
                </div>
                <div class="stat-item">
                    <div class="stat-val">0 GiB / ∞</div>
                    <div class="stat-lbl">ТРАФИК</div>
                </div>
            </div>

            <p style="text-align:center; font-size:12px;">Скопируйте URL этой страницы и импортируйте в Happ или v2rayNG</p>
            <a href="https://t.me/BotFather" class="btn">Открыть в Telegram</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html_page)
