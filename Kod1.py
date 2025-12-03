from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
import json
import aiohttp
import os
import wikipedia  # Новая библиотека

# Настраиваем язык Википедии на русский
wikipedia.set_lang("ru")

# Читаем токены из переменных окружения
TOKEN = os.getenv("TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

if not TOKEN or not WEATHER_API_KEY:
    raise RuntimeError("Установите переменные окружения TOKEN и WEATHER_API_KEY!")

# Хранение состояний
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(token=TOKEN)


# ───── Отдельные состояния для каждой функции ─────
class Form(StatesGroup):
    waiting_for_reminder = State()  # напоминания
    waiting_for_note = State()  # заметки
    waiting_for_city = State()  # погода
    waiting_for_ai = State()  # нейросеть
    waiting_for_wiki = State()  # википедия


# ───── ГЛАВНОЕ МЕНЮ ─────
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🧠 AI Помощник")],
        [KeyboardButton(text="🔍 Википедия"), KeyboardButton(text="🌤 Погода")],
        [KeyboardButton(text="⏰ Напомни позже"), KeyboardButton(text="📝 Заметки")],
        [KeyboardButton(text="💱 Курсы валют")]
    ],
    resize_keyboard=True
)


# ───── ПРИВЕТСТВИЕ ─────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я твой личный ассистент\n"
        "Чем помочь сегодня?",
        reply_markup=main_keyboard
    )


# ───── НЕЙРОСЕТЬ (AI) ─────
@dp.message(F.text == "🧠 AI Помощник")
async def ai_start(message: Message, state: FSMContext):
    ai_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Назад в меню")]],
        resize_keyboard=True
    )
    await message.answer(
        "🤖 Режим AI (GPT)\n"
        "Пиши любой вопрос, я отвечу.\n"
        "Для выхода нажми кнопку внизу.",
        reply_markup=ai_keyboard
    )
    await state.set_state(Form.waiting_for_ai)


@dp.message(Form.waiting_for_ai)
async def ai_chat(message: Message, state: FSMContext):
    if message.text == "Назад в меню":
        await message.answer("Выхожу из режима AI.", reply_markup=main_keyboard)
        await state.clear()
        return

    await bot.send_chat_action(message.chat.id, "typing")
    user_text = message.text
    url = "https://text.pollinations.ai/"

    payload = {
        "messages": [
            {"role": "system", "content": "Ты полезный ассистент. Отвечай кратко и по делу на русском."},
            {"role": "user", "content": user_text}
        ],
        "model": "openai"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    answer = await resp.text()
                    ai_keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад в меню")]],
                                                      resize_keyboard=True)
                    await message.answer(answer, reply_markup=ai_keyboard)
                else:
                    await message.answer("Ошибка AI сервера.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ───── ВИКИПЕДИЯ ─────
@dp.message(F.text == "🔍 Википедия")
async def wiki_start(message: Message, state: FSMContext):
    await message.answer(
        "Что найти в Википедии?\n"
        "Напиши слово или фразу (например: «Эйнштейн» или «Капибара»)",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Form.waiting_for_wiki)


@dp.message(Form.waiting_for_wiki)
async def wiki_search(message: Message, state: FSMContext):
    query = message.text.strip()
    await bot.send_chat_action(message.chat.id, "typing")

    try:
        # Ищем summary (краткое содержание), ограничиваем до 4 предложений
        result = wikipedia.summary(query, sentences=4)
        # Добавляем ссылку на статью
        page = wikipedia.page(query, auto_suggest=False)
        url = page.url

        text = f"📖 <b>{query}</b>\n\n{result}\n\n🔗 <a href='{url}'>Читать полностью</a>"
        await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard)

    except wikipedia.exceptions.DisambiguationError as e:
        # Если найдено много значений (например, "Наполеон" - торт и человек)
        options = ", ".join(e.options[:5])
        await message.answer(f"⚠️ Слишком много значений. Возможно, вы имели в виду:\n{options}",
                             reply_markup=main_keyboard)
    except wikipedia.exceptions.PageError:
        await message.answer("😔 Ничего не найдено по этому запросу.", reply_markup=main_keyboard)
    except Exception:
        await message.answer("Ошибка поиска. Попробуй другое слово.", reply_markup=main_keyboard)

    await state.clear()


# ───── УМНЫЕ НАПОМИНАНИЯ ─────
async def schedule_reminder(text: str, minutes: int, user_id: int):
    await asyncio.sleep(minutes * 60)
    try:
        await bot.send_message(user_id, f"⏰ Напоминание!\n{text}", reply_markup=main_keyboard)
    except:
        pass


@dp.message(F.text == "⏰ Напомни позже")
async def remind_later_start(message: Message, state: FSMContext):
    await message.answer(
        "Напиши, что напомнить и через сколько\n(Например: Позвонить другу через 20 минут)",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Form.waiting_for_reminder)


@dp.message(Form.waiting_for_reminder)
async def reminder_received(message: Message, state: FSMContext):
    text = message.text.lower()
    minutes_total = 0
    units = {
        'минут': 1, 'мин': 1, 'м': 1,
        'час': 60, 'ч': 60,
        'день': 1440, 'д': 1440
    }

    words = text.split()
    i = 0
    while i < len(words):
        word = words[i]
        if word.isdigit():
            num = int(word)
            if i + 1 < len(words):
                next_word = words[i + 1]
                for unit, multiplier in units.items():
                    if next_word.startswith(unit):
                        minutes_total += num * multiplier
                        i += 1
                        break
        i += 1

    if minutes_total == 0:
        await message.answer("Не понял время 🤷‍♂️\nПопробуй через меню.", reply_markup=main_keyboard)
        await state.clear()
        return

    # Расчет времени для красивого вывода
    days = minutes_total // 1440
    hours = (minutes_total % 1440) // 60
    mins = minutes_total % 60
    time_str = f"{days}д {hours}ч {mins}м" if days else f"{hours}ч {mins}м" if hours else f"{mins} мин"

    await message.answer(f"✅ Поставил таймер на {time_str}", reply_markup=main_keyboard)
    asyncio.create_task(schedule_reminder(message.text, minutes_total, message.from_user.id))
    await state.clear()


# ───── ЗАМЕТКИ ─────
NOTES_FILE = Path("notes.json")
if not NOTES_FILE.exists():
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f)


def load_notes():
    try:
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_notes_to_file(notes_data):
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(notes_data, f, ensure_ascii=False, indent=2)


@dp.message(F.text == "📝 Заметки")
async def show_notes_menu(message: Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить заметку"), KeyboardButton(text="Мои заметки")],
            [KeyboardButton(text="Назад в меню")]
        ],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Управление заметками:", reply_markup=keyboard)


@dp.message(F.text == "Добавить заметку")
async def add_note_start(message: Message, state: FSMContext):
    await message.answer("Пиши текст заметки:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_note)


@dp.message(Form.waiting_for_note)
async def save_note(message: Message, state: FSMContext):
    user_id = str(message.from_user.id)
    user_notes = load_notes()
    if user_id not in user_notes:
        user_notes[user_id] = []
    user_notes[user_id].append(message.text)
    save_notes_to_file(user_notes)
    await message.answer("✅ Сохранено!", reply_markup=main_keyboard)
    await state.clear()


@dp.message(F.text == "Мои заметки")
async def show_my_notes(message: Message):
    user_id = str(message.from_user.id)
    notes = load_notes().get(user_id, [])
    if not notes:
        await message.answer("Список пуст.", reply_markup=main_keyboard)
    else:
        text = "\n".join(f"{i + 1}. {note}" for i, note in enumerate(notes))
        await message.answer(f"📋 Твои заметки:\n\n{text}", reply_markup=main_keyboard)


@dp.message(F.text == "Назад в меню")
async def back_to_main(message: Message):
    await message.answer("Меню:", reply_markup=main_keyboard)


# ───── ПОГОДА ─────
@dp.message(F.text == "🌤 Погода")
async def weather_start(message: Message, state: FSMContext):
    await message.answer("Введи название города:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_city)


@dp.message(Form.waiting_for_city)
async def get_weather(message: Message, state: FSMContext):
    city = message.text.strip()
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                temp = data["main"]["temp"]
                desc = data["weather"][0]["description"].capitalize()
                await message.answer(f"🌤 {city}: {desc}, {temp}°C", reply_markup=main_keyboard)
            else:
                await message.answer("Не нашел такой город.", reply_markup=main_keyboard)
    await state.clear()


# ───── КУРСЫ ВАЛЮТ ─────
@dp.message(F.text == "💱 Курсы валют")
async def real_rates(message: Message):
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = json.loads(await resp.text())
                    usd = data["Valute"]["USD"]["Value"]
                    eur = data["Valute"]["EUR"]["Value"]
                    cny = data["Valute"]["CNY"]["Value"]
                    await message.answer(f"USD: {usd:.2f}₽\nEUR: {eur:.2f}₽\nCNY: {cny:.2f}₽",
                                         reply_markup=main_keyboard)
    except:
        await message.answer("Ошибка получения курсов", reply_markup=main_keyboard)


# ───── ОБРАБОТКА ВСЕГО ОСТАЛЬНОГО ─────
@dp.message()
async def echo(message: Message):
    await message.answer("Я не понял команду 🤖\nЖми кнопки!", reply_markup=main_keyboard)


# ───── ЗАПУСК ─────
async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Выключено вручную")