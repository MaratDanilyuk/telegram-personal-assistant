from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
import re
import json
import aiohttp
import os

# Читаем токены из переменных окружения (безопасно!)
TOKEN = os.getenv("TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

#TOKEN = "8290463822:AAFTrLhXf3PmvLN7ZEom4X80Onk_fHHx-zM"
#WEATHER_API_KEY = "806524453c5269ec6316eb29ddcb568b"   # твой ключ

# Хранение состояний
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot = Bot(token=TOKEN)

# ───── Отдельные состояния для каждой функции ─────
class Form(StatesGroup):
    waiting_for_reminder = State()   # напоминания
    waiting_for_note     = State()   # заметки
    waiting_for_city     = State()   # погода

# ───── Клавиатуры ─────
start_button = KeyboardButton(text="Запустить бота")
request_start = ReplyKeyboardMarkup(keyboard=[[start_button]], resize_keyboard=True, one_time_keyboard=True)

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Напомни позже"), KeyboardButton(text="Заметки")],
        [KeyboardButton(text="Погода"), KeyboardButton(text="Курсы валют")],
        [KeyboardButton(text="Случайная идея"), KeyboardButton(text="Помощь")]
    ],
    resize_keyboard=True
)

# ───── Запуск бота ─────
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет! Я твой личный ассистент\nНажми кнопку ниже, чтобы начать:", reply_markup=request_start)

@dp.message(F.text == "Запустить бота")
async def real_start(message: Message):
    await message.answer("Готово! Теперь я твой помощник 24/7\nЧем помочь?", reply_markup=main_keyboard)

# ───── Напоминания ─────
async def schedule_reminder(text: str, minutes: int, user_id: int):
    await asyncio.sleep(minutes * 60)
    await bot.send_message(user_id, f"Напоминание!\n{text}")

@dp.message(F.text == "Напомни позже")
async def remind_later_start(message: Message, state: FSMContext):
    await message.answer("Напиши, что напомнить и через сколько минут\nПример: «Позвонить маме через 15»",
                         reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_reminder)

@dp.message(Form.waiting_for_reminder)
async def reminder_received(message: Message, state: FSMContext):
    text = message.text.strip()
    numbers = re.findall(r'\d+', text)

    if not numbers:
        await message.answer("Не нашёл число минут\nПопробуй ещё раз:")
        return

    minutes = int(numbers[-1])
    if minutes < 1 or minutes > 1440:
        await message.answer("Укажи от 1 до 1440 минут")
        return

    await message.answer(f"Хорошо! Напомню через {minutes} минут", reply_markup=main_keyboard)
    asyncio.create_task(schedule_reminder(text, minutes, message.from_user.id))
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

@dp.message(F.text == "Курсы валют")
async def real_rates(message: Message):
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                # ←←←←← ВОТ ЭТА СТРОЧКА ЧИНИТ ВСЁ
                raw_text = await resp.text()
                data = json.loads(raw_text)
                # →→→→→
                usd = data["Valute"]["USD"]["Value"]
                eur = data["Valute"]["EUR"]["Value"]
                cny = data["Valute"]["CNY"]["Value"]  # добавил юань — красиво же
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
    await message.answer("Я умею:\n• Напоминания\n• Заметки (сохраняются навсегда)\n• Погода\n• Курсы валют\n• Случайные идеи")

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