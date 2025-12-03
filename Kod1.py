from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio, json, aiohttp, os, wikipedia, random

# Настройки
wikipedia.set_lang("ru")
TOKEN = os.getenv("TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

if not TOKEN or not WEATHER_API_KEY:
    raise RuntimeError("Нет переменных окружения!")

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(token=TOKEN)


# Состояния
class Form(StatesGroup):
    waiting_for_reminder = State()
    waiting_for_note = State()
    waiting_for_city = State()
    waiting_for_ai = State()
    waiting_for_wiki = State()


# Клавиатуры
main_kb = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="🧠 AI Помощник")],
    [KeyboardButton(text="🔍 Википедия"), KeyboardButton(text="🌤 Погода")],
    [KeyboardButton(text="⏰ Напомни позже"), KeyboardButton(text="📝 Заметки")],
    [KeyboardButton(text="💱 Курсы валют")]
], resize_keyboard=True)

back_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад в меню")]], resize_keyboard=True)


# ───── СТАРТ ─────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет! Я твой ассистент. Чем помочь?", reply_markup=main_kb)


@dp.message(F.text == "Назад в меню")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=main_kb)


# ───── НЕЙРОСЕТЬ ─────
@dp.message(F.text == "🧠 AI Помощник")
async def ai_start(message: Message, state: FSMContext):
    await message.answer("🤖 Режим AI (GPT). Спрашивай!\nВыход — кнопка внизу.", reply_markup=back_kb)
    await state.set_state(Form.waiting_for_ai)


@dp.message(Form.waiting_for_ai)
async def ai_chat(message: Message):
    await bot.send_chat_action(message.chat.id, "typing")
    payload = {
        "messages": [{"role": "system", "content": "Ты полезный ассистент. Отвечай кратко на русском."},
                     {"role": "user", "content": message.text}],
        "model": "openai"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://text.pollinations.ai/", json=payload) as resp:
                if resp.status == 200:
                    await message.answer(await resp.text(), reply_markup=back_kb)
                else:
                    await message.answer("Ошибка сервера AI.", reply_markup=back_kb)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ───── ВИКИПЕДИЯ ─────
@dp.message(F.text == "🔍 Википедия")
async def wiki_start(message: Message, state: FSMContext):
    await message.answer("Напиши слово для поиска:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_wiki)


@dp.message(Form.waiting_for_wiki)
async def wiki_search(message: Message, state: FSMContext):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        res = wikipedia.summary(message.text.strip(), sentences=4)
        url = wikipedia.page(message.text.strip(), auto_suggest=False).url
        await message.answer(f"📖 <b>{message.text}</b>\n\n{res}\n\n🔗 <a href='{url}'>Читать</a>",
                             parse_mode="HTML", reply_markup=main_kb)
    except wikipedia.exceptions.DisambiguationError as e:
        await message.answer(f"⚠️ Много значений: {', '.join(e.options[:5])}", reply_markup=main_kb)
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
    # Сокращенный словарь (startswith покроет 'минуты', 'часов' и т.д.)
    units = {'мин': 1, 'м': 1, 'час': 60, 'ч': 60, 'ден': 1440, 'дн': 1440}
    words = text.split()

    for i, word in enumerate(words):
        if word.isdigit() and i + 1 < len(words):
            key = next((k for k in units if words[i + 1].startswith(k)), None)
            if key: total_mins += int(word) * units[key]

    if total_mins == 0 or total_mins > 43200:
        await message.answer("Не понял время или > 30 дней. Попробуй еще раз.", reply_markup=main_kb)
    else:
        d, h, m = total_mins // 1440, (total_mins % 1440) // 60, total_mins % 60
        t_str = f"{d}д {h}ч {m}м" if d else f"{h}ч {m}м" if h else f"{m} мин"
        await message.answer(f"✅ Таймер на {t_str}", reply_markup=main_kb)
        asyncio.create_task(schedule_reminder(message.text, total_mins, message.from_user.id))
    await state.clear()


# ───── ЗАМЕТКИ ─────
NOTES_FILE = Path("notes.json")
if not NOTES_FILE.exists(): json.dump({}, open(NOTES_FILE, "w", encoding="utf-8"))


def manage_notes(data=None):
    if data is None:  # Load
        return json.load(open(NOTES_FILE, "r", encoding="utf-8"))
    json.dump(data, open(NOTES_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


@dp.message(F.text == "📝 Заметки")
async def notes_menu(message: Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Добавить заметку"), KeyboardButton(text="Мои заметки")],
        [KeyboardButton(text="Назад в меню")]], resize_keyboard=True)
    await message.answer("Меню заметок:", reply_markup=kb)


@dp.message(F.text == "Добавить заметку")
async def add_note(message: Message, state: FSMContext):
    await message.answer("Пиши текст:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_note)


@dp.message(Form.waiting_for_note)
async def save_note(message: Message, state: FSMContext):
    data, uid = manage_notes(), str(message.from_user.id)
    data.setdefault(uid, []).append(message.text)
    manage_notes(data)
    await message.answer("✅ Сохранено!", reply_markup=main_kb)
    await state.clear()


@dp.message(F.text == "Мои заметки")
async def list_notes(message: Message):
    notes = manage_notes().get(str(message.from_user.id), [])
    text = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(notes)) if notes else "Пусто."
    await message.answer(f"📋 Твои заметки:\n\n{text}", reply_markup=main_kb)


# ───── ПОГОДА И ВАЛЮТА ─────
@dp.message(F.text == "🌤 Погода")
async def weather_start(message: Message, state: FSMContext):
    await message.answer("Город?", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_city)


@dp.message(Form.waiting_for_city)
async def get_weather(message: Message, state: FSMContext):
    city = message.text.strip()
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url) as resp:
            if resp.status == 200:
                d = await resp.json()
                await message.answer(f"🌤 {city}: {d['weather'][0]['description']}, {d['main']['temp']}°C",
                                     reply_markup=main_kb)
            else:
                await message.answer("Не нашел город.", reply_markup=main_kb)
    await state.clear()


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


# ───── ЭХО И ЗАПУСК ─────
@dp.message()
async def echo(message: Message):
    await message.answer("Я не понял команду 🤖", reply_markup=main_kb)


async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Выключено вручную")