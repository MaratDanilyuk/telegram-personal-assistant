import asyncio, json, aiohttp, os, wikipedia, aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Настройки
wikipedia.set_lang("ru")
TOKEN = os.getenv("TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
DB_NAME = "bot_database.db"

if not TOKEN or not WEATHER_API_KEY: raise RuntimeError("Нет переменных окружения!")

dp = Dispatcher(storage=MemoryStorage())
bot = Bot(token=TOKEN)


class Form(StatesGroup):
    waiting_for_reminder = State()
    waiting_for_note = State()
    waiting_for_note_delete = State()  # Новое состояние для удаления
    waiting_for_city = State()
    waiting_for_ai = State()
    waiting_for_wiki = State()


# Клавиатуры
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🧠 AI Помощник"), KeyboardButton(text="🔍 Википедия")],
    [KeyboardButton(text="🌤 Погода"), KeyboardButton(text="💱 Курсы валют")],
    [KeyboardButton(text="⏰ Напомни позже"), KeyboardButton(text="📝 Заметки")]
], resize_keyboard=True)

back_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад в меню")]], resize_keyboard=True)


# ───── РАБОТА С БД ─────
async def db_exec(sql, params=()):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(sql, params)
        await db.commit()


async def db_fetch(sql, params=()):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(sql, params) as c:
            return [r[0] for r in await c.fetchall()]


# ───── ОБЩИЕ ФУНКЦИИ ─────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await db_exec("CREATE TABLE IF NOT EXISTS notes (user_id INTEGER, text TEXT)")
    await message.answer("Привет! Я твой цифровой ассистент. Чем помочь?", reply_markup=main_kb)


@dp.message(F.text == "Назад в меню")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_kb)

# Словарь для хранения истории диалога: {user_id: [список сообщений]}
user_context = {}

# ───── НЕЙРОСЕТЬ ─────
@dp.message(F.text == "🧠 AI Помощник")
async def ai_start(message: Message, state: FSMContext):
    # При входе очищаем старую историю, чтобы начать диалог с чистого листа
    user_context[message.from_user.id] = [
        {"role": "system", "content": "Ты умный ассистент. Отвечай на русском."}
    ]
    await message.answer("🤖 Режим GPT. Я помню контекст беседы!\nСпрашивай. Выход — кнопка внизу.",
                         reply_markup=back_kb)
    await state.set_state(Form.waiting_for_ai)

@dp.message(Form.waiting_for_ai)
async def ai_chat(message: Message):
    user_id = message.from_user.id

    # Если истории почему-то нет (перезагрузка бота), создаем новую
    if user_id not in user_context:
        user_context[user_id] = [{"role": "system", "content": "Ты умный ассистент."}]

    # Добавляем сообщение пользователя в историю
    user_context[user_id].append({"role": "user", "content": message.text})
    await bot.send_chat_action(message.chat.id, "typing")

    try:
        async with aiohttp.ClientSession() as sess:
            # Отправляем ВСЮ историю (user_context), а не только message.text
            payload = {
                "messages": user_context[user_id],
                "model": "openai"
            }
            async with sess.post("https://text.pollinations.ai/", json=payload) as resp:
                if resp.status == 200:
                    answer = await resp.text()
                    # Добавляем ответ бота в историю, чтобы он тоже его помнил
                    user_context[user_id].append({"role": "assistant", "content": answer})
                    await message.answer(answer, reply_markup=back_kb)
                else:
                    await message.answer("Ошибка сервера.", reply_markup=back_kb)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# ───── ВИКИПЕДИЯ ─────
@dp.message(F.text == "🔍 Википедия")
async def wiki_start(message: Message, state: FSMContext):
    await message.answer("Введи запрос для поиска:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_wiki)


@dp.message(Form.waiting_for_wiki)
async def wiki_search(message: Message, state: FSMContext):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        res = wikipedia.summary(message.text.strip(), sentences=4)
        url = wikipedia.page(message.text.strip(), auto_suggest=False).url
        await message.answer(f"📖 <b>{message.text}</b>\n\n{res}\n\n🔗 <a href='{url}'>Читать статью</a>",
                             parse_mode="HTML", reply_markup=main_kb)
    except Exception:
        await message.answer("Ничего не найдено.", reply_markup=main_kb)
    await state.clear()


# ───── НАПОМИНАНИЯ ─────
async def schedule_reminder(text, mins, user_id):
    await asyncio.sleep(mins * 60)
    try:
        await bot.send_message(user_id, f"⏰ Напоминание!\n{text}", reply_markup=main_kb)
    except:
        pass


@dp.message(F.text == "⏰ Напомни позже")
async def remind_start(message: Message, state: FSMContext):
    await message.answer("Что напомнить и через сколько? (напр: 'Воду через 10 мин')",
                         reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_reminder)


@dp.message(Form.waiting_for_reminder)
async def remind_parse(message: Message, state: FSMContext):
    text, total_mins = message.text.lower(), 0
    units = {'мин': 1, 'м': 1, 'час': 60, 'ч': 60, 'ден': 1440, 'дн': 1440}
    words = text.split()

    for i, word in enumerate(words):
        if word.isdigit() and i + 1 < len(words):
            key = next((k for k in units if words[i + 1].startswith(k)), None)
            if key: total_mins += int(word) * units[key]

    if 0 < total_mins <= 43200:
        d, h, m = total_mins // 1440, (total_mins % 1440) // 60, total_mins % 60
        t_str = f"{d}д {h}ч {m}м" if d else f"{h}ч {m}м" if h else f"{m} мин"
        await message.answer(f"✅ Таймер на {t_str}", reply_markup=main_kb)
        asyncio.create_task(schedule_reminder(message.text, total_mins, message.from_user.id))
    else:
        await message.answer("Не понял время или срок > 30 дней.", reply_markup=main_kb)
    await state.clear()


# ───── ЗАМЕТКИ ─────
@dp.message(F.text == "📝 Заметки")
async def notes_menu(message: Message):
    # Обновленная клавиатура с кнопкой Удалить
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Добавить"), KeyboardButton(text="Удалить")],
        [KeyboardButton(text="Мои заметки"), KeyboardButton(text="Назад в меню")]
    ], resize_keyboard=True)
    await message.answer("Меню заметок:", reply_markup=kb)


@dp.message(F.text == "Добавить")
async def add_note(message: Message, state: FSMContext):
    await message.answer("Введи текст заметки:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_note)


@dp.message(Form.waiting_for_note)
async def save_note(message: Message, state: FSMContext):
    await db_exec("INSERT INTO notes (user_id, text) VALUES (?, ?)", (message.from_user.id, message.text))
    await message.answer("✅ Сохранено!", reply_markup=main_kb)
    await state.clear()


@dp.message(F.text == "Мои заметки")
async def list_notes(message: Message):
    notes = await db_fetch("SELECT text FROM notes WHERE user_id = ?", (message.from_user.id,))
    text = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(notes)) if notes else "Список пуст."
    await message.answer(f"📋 Твои заметки:\n\n{text}", reply_markup=main_kb)


@dp.message(F.text == "Удалить")
async def delete_note_start(message: Message, state: FSMContext):
    # Сначала показываем список, чтобы юзер знал номер
    notes = await db_fetch("SELECT text FROM notes WHERE user_id = ?", (message.from_user.id,))
    if not notes:
        await message.answer("Удалять нечего, список пуст.", reply_markup=main_kb)
        return
    text = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(notes))
    await message.answer(f"📋 Выбери номер заметки для удаления:\n\n{text}", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_note_delete)


@dp.message(Form.waiting_for_note_delete)
async def delete_note_finish(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Нужно ввести число!", reply_markup=main_kb)
        await state.clear()
        return

    num = int(message.text)
    # Хитрый SQL: удаляем N-ю запись пользователя
    # LIMIT 1 OFFSET (N-1) находит нужную строку, а мы берем её ID и удаляем
    sql = """
        DELETE FROM notes 
        WHERE rowid = (
            SELECT rowid FROM notes 
            WHERE user_id = ? 
            LIMIT 1 OFFSET ?
        )
    """
    await db_exec(sql, (message.from_user.id, num - 1))
    await message.answer("🗑 Заметка удалена (если номер был верный).", reply_markup=main_kb)
    await state.clear()


# ───── ПОГОДА ─────
@dp.message(F.text == "🌤 Погода")
async def weather_start(message: Message, state: FSMContext):
    await message.answer("Введи город:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_city)


@dp.message(Form.waiting_for_city)
async def get_weather(message: Message, state: FSMContext):
    city = message.text.strip()
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url) as resp:
            if resp.status == 200:
                d = await resp.json()
                text = (f"🌤 <b>{city}</b>\n🌡 Темп: {round(d['main']['temp'])}°C\n"
                        f"🥶 Ощущается: <b>{round(d['main']['feels_like'])}°C</b>\n📝 {d['weather'][0]['description'].capitalize()}")
                await message.answer(text, parse_mode="HTML", reply_markup=main_kb)
            else:
                await message.answer("Город не найден.", reply_markup=main_kb)
    await state.clear()


# ───── КУРСЫ ─────
@dp.message(F.text == "💱 Курсы валют")
async def get_rates(message: Message):
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get("https://www.cbr-xml-daily.ru/daily_json.js") as resp:
                d = json.loads(await resp.text())["Valute"]
                await message.answer(
                    f"USD: {d['USD']['Value']:.2f}₽\nEUR: {d['EUR']['Value']:.2f}₽\nCNY: {d['CNY']['Value']:.2f}₽",
                    reply_markup=main_kb)
    except:
        await message.answer("Ошибка курсов", reply_markup=main_kb)


@dp.message()
async def echo(message: Message):
    await message.answer("Не понял команду 🤖", reply_markup=main_kb)


if __name__ == "__main__":
    try:
        print("Бот запущен!")
        asyncio.run(dp.start_polling(bot))
    except KeyboardInterrupt:
        print("Выключено вручную")