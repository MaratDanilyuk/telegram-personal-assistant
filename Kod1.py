from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
import json
import aiohttp
import os

# Читаем токены из переменных окружения (безопасно!)
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
    waiting_for_reminder = State()   # напоминания
    waiting_for_note     = State()   # заметки
    waiting_for_city     = State()   # погода

# ───── ГЛАВНОЕ МЕНЮ (сразу показываем при старте) ─────
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Напомни позже"), KeyboardButton(text="Заметки")],
        [KeyboardButton(text="Погода"), KeyboardButton(text="Курсы валют")],
        [KeyboardButton(text="Случайная идея"), KeyboardButton(text="Помощь")]
    ],
    resize_keyboard=True
)

# ───── ПРИВЕТСТВИЕ СРАЗУ С МЕНЮ (без кнопки "Запустить бота") ─────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я твой личный ассистент\n"
        "Чем помочь сегодня?",
        reply_markup=main_keyboard
    )

# ───── УМНЫЕ НАПОМИНАНИЯ: минуты + часы + дни ─────
async def schedule_reminder(text: str, minutes: int, user_id: int):
    await asyncio.sleep(minutes * 60)
    await bot.send_message(user_id, f"Напоминание!\n{text}")

@dp.message(F.text == "Напомни позже")
async def remind_later_start(message: Message, state: FSMContext):
    await message.answer(
        "Напиши, что напомнить и через сколько\n\n"
        "Примеры:\n"
        "• Позвонить маме через 2 часа\n"
        "• Сходить в магазин через 3 дня\n"
        "• Выпить воду через 45 минут\n"
        "• Встреча через 1 день 5 часов",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(Form.waiting_for_reminder)

@dp.message(Form.waiting_for_reminder)
async def reminder_received(message: Message, state: FSMContext):
    original_text = message.text.strip()
    text = original_text.lower()

    minutes_total = 0
    units = {
        'минут': 1, 'минуты': 1, 'минуту': 1, 'минута': 1, 'мин': 1, 'м': 1,
        'час': 60, 'часа': 60, 'часов': 60, 'ч': 60,
        'день': 1440, 'дня': 1440, 'дней': 1440, 'д': 1440
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
        await message.answer("Не понял время\nПримеры: через 10 минут / 2 часа / 1 день")
        return

    if minutes_total > 43200:  # 30 дней
        await message.answer("Слишком далеко — максимум 30 дней")
        return

    # Красивое подтверждение
    days = minutes_total // 1440
    hours = (minutes_total % 1440) // 60
    mins = minutes_total % 60
    parts = []
    if days: parts.append(f"{days} дн.")
    if hours: parts.append(f"{hours} ч.")
    if mins: parts.append(f"{mins} мин.")
    time_str = " ".join(parts) if parts else "чуть позже"

    await message.answer(f"Хорошо! Напомню через {time_str}", reply_markup=main_keyboard)
    asyncio.create_task(schedule_reminder(original_text, minutes_total, message.from_user.id))
    await state.clear()

# ───── Заметки (с сохранением в файл) ─────
NOTES_FILE = Path("notes.json")
if NOTES_FILE.exists():
    with open(NOTES_FILE, "r", encoding="utf-8") as f:
        user_notes = json.load(f)
else:
    user_notes = {}

def save_notes():
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(user_notes, f, ensure_ascii=False, indent=2)

@dp.message(F.text == "Заметки")
async def show_notes_menu(message: Message):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Добавить заметку")],
            [KeyboardButton(text="Мои заметки")],
            [KeyboardButton(text="Назад в меню")]
        ],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Что сделать с заметками?", reply_markup=keyboard)

@dp.message(F.text == "Добавить заметку")
async def add_note_start(message: Message, state: FSMContext):
    await message.answer("Напиши заметку — сохраню навсегда", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_note)

@dp.message(Form.waiting_for_note)
async def save_note(message: Message, state: FSMContext):
    text = message.text.strip()
    user_id = str(message.from_user.id)
    if user_id not in user_notes:
        user_notes[user_id] = []
    user_notes[user_id].append(text)
    save_notes()
    await message.answer(f"Заметка сохранена!\n\n«{text}»", reply_markup=main_keyboard)
    await state.clear()

@dp.message(F.text == "Мои заметки")
async def show_my_notes(message: Message):
    user_id = str(message.from_user.id)
    notes_list = user_notes.get(user_id, [])
    if not notes_list:
        await message.answer("У тебя пока нет заметок\nДобавь первую!", reply_markup=main_keyboard)
    else:
        text = "Твои заметки:\n\n" + "\n".join(f"{i}. {note}" for i, note in enumerate(notes_list, 1))
        await message.answer(text, reply_markup=main_keyboard)

@dp.message(F.text == "Назад в меню")
async def back_to_main(message: Message):
    await message.answer("Главное меню:", reply_markup=main_keyboard)

# ───── Погода ─────
@dp.message(F.text == "Погода")
async def weather_start(message: Message, state: FSMContext):
    await message.answer("Напиши название города")
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
                await message.answer(f"Погода в {city}:\n{desc}, {temp}°C", reply_markup=main_keyboard)
            else:
                await message.answer("Город не найден\nПопробуй ещё раз")
    await state.clear()

# ───── Курсы валют ─────
@dp.message(F.text == "Курсы валют")
async def real_rates(message: Message):
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                raw_text = await resp.text()
                data = json.loads(raw_text)
                usd = data["Valute"]["USD"]["Value"]
                eur = data["Valute"]["EUR"]["Value"]
                cny = data["Valute"]["CNY"]["Value"]
                await message.answer(
                    f"Курсы ЦБ РФ на сегодня:\n\n"
                    f"USD → {usd:.2f} ₽\n"
                    f"EUR → {eur:.2f} ₽\n"
                    f"CNY → {cny:.2f} ₽"
                )
            else:
                await message.answer("Не смог получить курсы")

# ───── Остальные кнопки ─────
@dp.message(F.text == "Случайная идея")
async def idea(message: Message):
    ideas = ["Сделай 10 отжиманий", "Выпей стакан воды", "Позвони другу", "Улыбнись в зеркало", "Сделай глубокий вдох"]
    import random
    await message.answer(random.choice(ideas))

@dp.message(F.text == "Помощь")
async def help_cmd(message: Message):
    await message.answer("Я умею:\n• Напоминания (мин/ч/дни)\n• Заметки\n• Погода\n• Курсы валют\n• Случайные идеи")

# ───── Эхо ─────
@dp.message()
async def echo(message: Message):
    await message.answer("Не понял команды\nВыбери кнопку из меню")

# ───── Запуск ─────
async def main():
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())