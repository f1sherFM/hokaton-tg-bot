import os
import logging
import asyncio
from typing import Optional, List, Dict, Any
import psycopg2
from psycopg2 import sql, extras
import requests
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Конфигурация
class Config:
    # Настройки базы данных
    DB_NAME = "sport_bot_db"
    DB_USER = "postgres"
    DB_PASSWORD = "root"
    DB_HOST = "localhost"
    DB_PORT = "5432"
    
    # Настройки Telegram бота
    TELEGRAM_TOKEN = "5354843188:AAGw7HfazJXuxlruAMTYesFCHljTBahfHgk"
    
    # Настройки Mistral AI
    MISTRAL_API_KEY = "nG2ac1xdGlnSHW2U7IEee6HADxcPf7fY"
    MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
    MISTRAL_MODEL = "mistral-small"
    
    # Настройки уровней
    XP_PER_VISIT = 10
    LEVEL_UP_XP_FACTOR = 100

# Инициализация бота с новым синтаксисом
bot = Bot(
    token=Config.TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# Состояния пользователя
class UserStates(StatesGroup):
    waiting_for_sport_type = State()
    waiting_for_age_group = State()
    waiting_for_location = State()
    waiting_for_feedback = State()

# Класс для работы с базой данных
class Database:
    def __init__(self):
        self.conn = None
        
    async def connect(self):
        try:
            self.conn = psycopg2.connect(
                dbname=Config.DB_NAME,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                host=Config.DB_HOST,
                port=Config.DB_PORT
            )
            logger.info("Successfully connected to PostgreSQL database")
        except Exception as e:
            logger.error(f"Error connecting to PostgreSQL: {e}")
            raise
            
    async def close(self):
        if self.conn:
            self.conn.close()
            logger.info("Closed database connection")
            
    async def execute_query(self, query: str, params: tuple = None, fetch: bool = False):
        try:
            with self.conn.cursor(cursor_factory=extras.DictCursor) as cur:
                cur.execute(query, params or ())
                if fetch:
                    return cur.fetchall()
                self.conn.commit()
        except Exception as e:
            logger.error(f"Database error: {e}")
            self.conn.rollback()
            raise
            
    async def init_db(self):
        """Инициализация таблиц в базе данных"""
        queries = [
            """
            CREATE TABLE IF NOT EXISTS sports_facilities (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                type VARCHAR(100) NOT NULL,
                address TEXT NOT NULL,
                sports TEXT[] NOT NULL,
                age_groups VARCHAR(100)[] NOT NULL,
                schedule JSONB,
                contacts VARCHAR(255),
                coordinates POINT,
                description TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(100),
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                registration_date TIMESTAMP DEFAULT NOW(),
                current_level INTEGER DEFAULT 1,
                experience_points INTEGER DEFAULT 0,
                last_activity_date DATE,
                preferences TEXT[]
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS user_visits (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                facility_id INTEGER REFERENCES sports_facilities(id),
                visit_date TIMESTAMP DEFAULT NOW(),
                activity_type VARCHAR(100),
                rating INTEGER
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS achievements (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                achievement_name VARCHAR(255) NOT NULL,
                achievement_date TIMESTAMP DEFAULT NOW(),
                badge_url VARCHAR(255),
                description TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sport_events (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                event_date TIMESTAMP NOT NULL,
                location VARCHAR(255),
                organizer VARCHAR(255),
                age_restriction VARCHAR(100),
                registration_url VARCHAR(255)
            )
            """
        ]
        
        try:
            for query in queries:
                await self.execute_query(query)
            logger.info("Database tables initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

# Класс для работы с Mistral AI
class MistralAI:
    @staticmethod
    async def generate_response(prompt: str, context: str = None) -> str:
        headers = {
            "Authorization": f"Bearer {Config.MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt})
        
        data = {
            "model": Config.MISTRAL_MODEL,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 4096
        }
        
        try:
            response = requests.post(Config.MISTRAL_API_URL, headers=headers, json=data, timeout=10)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            logger.error(f"Mistral API request failed: {e}")
            return "Извините, возникла проблема при обработке вашего запроса. Пожалуйста, попробуйте позже."
        except Exception as e:
            logger.error(f"Error processing Mistral response: {e}")
            return "Извините, не удалось обработать ваш запрос."

# Инициализация компонентов
db = Database()
mistral = MistralAI()

# ======================
# Обработчики команд
# ======================

@router.message(Command("start"))
async def send_welcome(message: types.Message):
    """Обработка команды /start"""
    user = message.from_user
    
    # Регистрация пользователя в базе
    await db.execute_query(
        """
        INSERT INTO users (user_id, username, first_name, last_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user.id, user.username, user.first_name, user.last_name)
    )
    
    # Генерация персонализированного приветствия
    prompt = (
        f"Сгенерируй дружелюбное приветствие для нового пользователя спортивного чат-бота. "
        f"Имя пользователя: {user.first_name or 'друг'}. "
        f"Бот помогает находить спортивные объекты в Сургуте, записываться на тренировки и участвовать в челленджах. "
        f"Приветствие должно быть кратким (1-2 предложения), мотивирующим и включать эмодзи."
    )
    
    greeting = await mistral.generate_response(prompt)
    
    # Отправка приветственного сообщения
    await message.answer(
        f"{greeting}\n\n"
        "🏆 Я ваш персональный спортивный помощник в Сургуте!\n\n"
        "Вот что я умею:\n"
        "🔍 /find - Найти спортивные объекты\n"
        "📊 /stats - Моя статистика и уровень\n"
        "🏅 /achievements - Мои достижения\n"
        "🎯 /recommend - Персональные рекомендации\n"
        "🏁 /events - Ближайшие мероприятия\n\n"
        "Вы также можете задавать вопросы в свободной форме."
    )

@router.message(Command("help"))
async def send_help(message: types.Message):
    """Обработка команды /help"""
    help_text = (
        "🆘 <b>Помощь по использованию бота</b>\n\n"
        "<b>Основные команды:</b>\n"
        "🔍 /find - Поиск спортивных объектов по параметрам\n"
        "📊 /stats - Ваша статистика и уровень\n"
        "🏅 /achievements - Ваши достижения\n"
        "🎯 /recommend - Персональные рекомендации\n"
        "🏁 /events - Ближайшие спортивные мероприятия\n\n"
        "<b>Примеры запросов:</b>\n"
        "• Где можно заняться плаванием в центре города?\n"
        "• Какие есть секции для детей 10 лет?\n"
        "• Посоветуй интересные спортивные активности\n"
        "• Какие мероприятия будут в эти выходные?\n\n"
        "Чем чаще вы посещаете спортивные объекты, тем выше ваш уровень и больше достижений!"
    )
    await message.answer(help_text)

@router.message(Command("find"))
async def find_sports_facilities(message: types.Message, state: FSMContext):
    """Поиск спортивных объектов - начало диалога"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Футбол"), KeyboardButton(text="Хоккей")],
            [KeyboardButton(text="Плавание"), KeyboardButton(text="Йога")],
            [KeyboardButton(text="Тренажерный зал"), KeyboardButton(text="Другое")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await state.set_state(UserStates.waiting_for_sport_type)
    await message.answer(
        "⚽ <b>Какой вид спорта вас интересует?</b>",
        reply_markup=keyboard
    )

@router.message(StateFilter(UserStates.waiting_for_sport_type))
async def process_sport_type(message: types.Message, state: FSMContext):
    """Обработка выбора вида спорта"""
    sport_type = message.text
    
    # Сохраняем выбранный вид спорта
    await state.update_data(sport_type=sport_type)
    
    # Создаем клавиатуру для выбора возрастной группы
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Дети (до 12)"), KeyboardButton(text="Подростки (13-17)")],
            [KeyboardButton(text="Взрослые (18+)"), KeyboardButton(text="Все возрасты")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await state.set_state(UserStates.waiting_for_age_group)
    await message.answer(
        "👶 <b>Для какой возрастной группы ищем занятия?</b>",
        reply_markup=keyboard
    )

@router.message(StateFilter(UserStates.waiting_for_age_group))
async def process_age_group(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    sport_type = user_data.get('sport_type')
    age_group = message.text
    
    logger.info(f"Searching for: sport={sport_type}, age={age_group}")  # Логируем
    
    facilities = await db.execute_query(
        """SELECT name, sports, age_groups 
           FROM sports_facilities 
           WHERE %s = ANY(sports) AND %s = ANY(age_groups)""",
        (sport_type, age_group),
        fetch=True
    )
    
    logger.info(f"Found {len(facilities)} facilities")  # Логируем результат
    
    if not facilities:
        await message.answer(
            "😕 <b>Не нашел подходящих спортивных объектов по вашим критериям.</b>\n"
            "Попробуйте изменить параметры поиска или воспользуйтесь /recommend для персональных рекомендаций."
        )
        await state.clear()
        return
    
    # Формируем ответ
    response = ["<b>🏟 Найденные спортивные объекты:</b>\n\n"]
    for idx, facility in enumerate(facilities, 1):
        response.append(
            f"<b>{idx}. {facility['name']} ({facility['type']})</b>\n"
            f"📍 Адрес: {facility['address']}\n"
            f"🏷 Виды спорта: {', '.join(facility['sports'])}\n"
            f"👥 Возраст: {', '.join(facility['age_groups'])}\n"
            f"📞 Контакты: {facility['contacts'] or 'не указаны'}\n"
        )
        if facility['description']:
            response.append(f"📝 Описание: {facility['description']}\n")
        response.append("\n")
    
    # Добавляем предложение отметить посещение
    response.append(
        "После посещения вы можете отметить его командой /visit [номер], "
        "чтобы получить опыт и повысить уровень!"
    )
    
    # Сохраняем результаты поиска для последующего использования
    await state.update_data(search_results=facilities)
    await state.clear()
    
    await message.answer("".join(response))

@router.message(Command("visit"))
async def log_visit(message: types.Message, state: FSMContext):
    """Логирование посещения спортивного объекта"""
    try:
        # Парсим номер объекта из команды (/visit 1)
        args = message.text.split()
        if len(args) < 2:
            raise ValueError
        facility_num = int(args[1])
    except (ValueError, IndexError):
        await message.answer(
            "Пожалуйста, укажите номер объекта после команды, например:\n"
            "<code>/visit 1</code> - чтобы отметить посещение первого объекта из последнего поиска"
        )
        return
    
    # Получаем сохраненные результаты поиска
    user_data = await state.get_data()
    facilities = user_data.get('search_results', [])
    
    if not facilities or facility_num < 1 or facility_num > len(facilities):
        await message.answer(
            "Не удалось найти объект с таким номером. "
            "Пожалуйста, выполните поиск снова и укажите корректный номер."
        )
        return
    
    facility = facilities[facility_num - 1]
    user_id = message.from_user.id
    sport_type = facility['sports'][0] if facility['sports'] else 'unknown'
    
    try:
        # Добавляем запись о посещении
        await db.execute_query(
            """
            INSERT INTO user_visits (user_id, facility_id, activity_type)
            VALUES (%s, %s, %s)
            """,
            (user_id, facility['id'], sport_type)
        )
        
        # Обновляем опыт пользователя
        await db.execute_query(
            """
            UPDATE users 
            SET experience_points = experience_points + %s,
                last_activity_date = CURRENT_DATE
            WHERE user_id = %s
            """,
            (Config.XP_PER_VISIT, user_id)
        )
        
        # Проверяем повышение уровня
        user_data = await db.execute_query(
            """
            SELECT current_level, experience_points FROM users 
            WHERE user_id = %s
            """,
            (user_id,),
            fetch=True
        )
        
        if user_data:
            current_level = user_data[0]['current_level']
            current_xp = user_data[0]['experience_points']
            xp_needed = current_level * Config.LEVEL_UP_XP_FACTOR
            
            if current_xp >= xp_needed:
                new_level = current_level + 1
                await db.execute_query(
                    """
                    UPDATE users 
                    SET current_level = %s
                    WHERE user_id = %s
                    """,
                    (new_level, user_id)
                )
                
                # Отправляем уведомление о новом уровне
                await message.answer(
                    f"🎉 <b>Поздравляем! Вы достигли {new_level} уровня!</b>\n"
                    f"Продолжайте в том же духе и открывайте новые достижения!"
                )
                
                # Проверяем достижения
                if new_level == 3:
                    await grant_achievement(user_id, "Новичок", "Поздравляем с достижением 3 уровня!")
                elif new_level == 5:
                    await grant_achievement(user_id, "Любитель", "Вы достигли 5 уровня! Так держать!")
                elif new_level == 10:
                    await grant_achievement(user_id, "Профессионал", "10 уровень - впечатляющий результат!")
        
        await message.answer(
            f"✅ <b>Отлично! Вы отметили посещение {facility['name']}.</b>\n"
            f"+{Config.XP_PER_VISIT} опыта! Проверьте свой прогресс командой /stats"
        )
    except Exception as e:
        logger.error(f"Error logging visit: {e}")
        await message.answer(
            "Произошла ошибка при отметке посещения. Пожалуйста, попробуйте позже."
        )

async def grant_achievement(user_id: int, name: str, description: str):
    """Выдача достижения пользователю"""
    try:
        # Проверяем, есть ли уже такое достижение
        existing = await db.execute_query(
            """
            SELECT id FROM achievements 
            WHERE user_id = %s AND achievement_name = %s
            """,
            (user_id, name),
            fetch=True
        )
        
        if not existing:
            await db.execute_query(
                """
                INSERT INTO achievements (user_id, achievement_name, description)
                VALUES (%s, %s, %s)
                """,
                (user_id, name, description)
            )
            
            await bot.send_message(
                user_id,
                f"🏆 <b>Новое достижение: {name}!</b>\n"
                f"{description}\n\n"
                f"Посмотреть все достижения: /achievements"
            )
    except Exception as e:
        logger.error(f"Error granting achievement: {e}")

@router.message(Command("stats"))
async def show_user_stats(message: types.Message):
    """Показ статистики пользователя"""
    user_id = message.from_user.id
    
    try:
        user_data = await db.execute_query(
            """
            SELECT u.current_level, u.experience_points, u.registration_date, 
                   COUNT(v.id) as visits_count, 
                   STRING_AGG(DISTINCT v.activity_type, ', ') as activities
            FROM users u
            LEFT JOIN user_visits v ON u.user_id = v.user_id
            WHERE u.user_id = %s
            GROUP BY u.user_id
            """,
            (user_id,),
            fetch=True
        )
        
        if not user_data:
            await message.answer("Вы еще не зарегистрированы. Напишите /start")
            return
        
        user = user_data[0]
        level = user['current_level']
        xp = user['experience_points']
        visits = user['visits_count'] or 0
        activities = user['activities'] or "пока нет данных"
        reg_date = user['registration_date'].strftime("%d.%m.%Y")
        
        # Рассчитываем прогресс до следующего уровня
        xp_needed = level * Config.LEVEL_UP_XP_FACTOR
        progress_percent = min(int(xp / xp_needed * 100), 100)
        progress_bar = "🟩" * int(progress_percent / 10) + "⬜" * (10 - int(progress_percent / 10))
        
        # Генерируем персонализированное сообщение
        prompt = (
            f"Пользователь спортивного чат-бота запросил свою статистику. "
            f"Уровень: {level}, опыт: {xp}, посещений: {visits}. "
            f"Основные активности: {activities}. "
            f"Дата регистрации: {reg_date}. "
            "Напиши мотивирующее сообщение на 2-3 предложения, отмечая достижения "
            "и предлагая варианты для дальнейшего роста. Используй эмодзи."
        )
        
        ai_response = await mistral.generate_response(prompt)
        
        # Формируем ответ
        response = (
            f"<b>📊 Ваша спортивная статистика:</b>\n\n"
            f"🏅 <b>Уровень:</b> {level}\n"
            f"⭐ <b>Опыт:</b> {xp}/{xp_needed}\n"
            f"📈 <b>Прогресс:</b> {progress_bar} {progress_percent}%\n"
            f"🏋️‍♂️ <b>Всего посещений:</b> {visits}\n"
            f"⚽ <b>Основные активности:</b> {activities}\n"
            f"📅 <b>Дата регистрации:</b> {reg_date}\n\n"
            f"{ai_response}\n\n"
            f"Продолжайте тренировки! Каждое посещение приносит вам опыт."
        )
        
        await message.answer(response)
    except Exception as e:
        logger.error(f"Error showing stats: {e}")
        await message.answer(
            "Произошла ошибка при получении статистики. Пожалуйста, попробуйте позже."
        )

@router.message(Command("achievements"))
async def show_achievements(message: types.Message):
    """Показ достижений пользователя"""
    user_id = message.from_user.id
    
    try:
        achievements = await db.execute_query(
            """
            SELECT achievement_name, description, achievement_date 
            FROM achievements 
            WHERE user_id = %s
            ORDER BY achievement_date DESC
            """,
            (user_id,),
            fetch=True
        )
        
        if not achievements:
            await message.answer(
                "У вас пока нет достижений. 🏆\n"
                "Посещайте спортивные объекты, повышайте уровень и получайте достижения!"
            )
            return
        
        response = ["<b>🏆 Ваши достижения:</b>\n\n"]
        for ach in achievements:
            date_str = ach['achievement_date'].strftime("%d.%m.%Y")
            response.append(
                f"• <b>{ach['achievement_name']}</b> ({date_str})\n"
                f"   {ach['description']}\n\n"
            )
        
        await message.answer("".join(response))
    except Exception as e:
        logger.error(f"Error showing achievements: {e}")
        await message.answer(
            "Произошла ошибка при получении списка достижений. Пожалуйста, попробуйте позже."
        )

@router.message(Command("recommend"))
async def recommend_activities(message: types.Message):
    """Персональные рекомендации"""
    user_id = message.from_user.id
    
    try:
        # Получаем данные пользователя
        user_data = await db.execute_query(
            """
            SELECT u.current_level, u.experience_points, 
                   STRING_AGG(DISTINCT v.activity_type, ', ') as activities
            FROM users u
            LEFT JOIN user_visits v ON u.user_id = v.user_id
            WHERE u.user_id = %s
            GROUP BY u.user_id
            """,
            (user_id,),
            fetch=True
        )
        
        # Получаем популярные объекты
        facilities = await db.execute_query(
            """
            SELECT name, type, sports, age_groups, description 
            FROM sports_facilities 
            ORDER BY RANDOM() LIMIT 5
            """,
            fetch=True
        )
        
        # Формируем контекст для AI
        context = (
            "Ты - спортивный помощник для жителей Сургута. "
            "Пользователь запросил персональные рекомендации. "
            f"Уровень пользователя: {user_data[0]['current_level'] if user_data else 1}\n"
            f"Его основные активности: {user_data[0]['activities'] if user_data and user_data[0]['activities'] else 'пока нет данных'}\n\n"
            "Доступные спортивные объекты:\n"
        )
        
        for fac in facilities:
            context += (
                f"- {fac['name']} ({fac['type']}): {', '.join(fac['sports'])}, "
                f"возраст: {', '.join(fac['age_groups'])}\n"
                f"  Описание: {fac['description']}\n"
            )
        
        context += (
            "\nСгенерируй 2-3 персонализированные рекомендации для пользователя "
            "на основе его уровня и предпочтений. Ответ должен быть кратким, "
            "дружелюбным и мотивирующим. Используй эмодзи."
        )
        
        # Получаем рекомендации от AI
        recommendations = await mistral.generate_response(
            "Сгенерируй персональные спортивные рекомендации",
            context
        )
        
        await message.answer(
            f"🎯 <b>Персональные рекомендации для вас:</b>\n\n"
            f"{recommendations}\n\n"
            f"Хотите найти конкретные места? Напишите /find"
        )
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}")
        await message.answer(
            "Произошла ошибка при формировании рекомендаций. Пожалуйста, попробуйте позже."
        )

@router.message(Command("events"))
async def show_upcoming_events(message: types.Message):
    """Показ ближайших мероприятий"""
    try:
        events = await db.execute_query(
            """
            SELECT title, description, event_date, location 
            FROM sport_events 
            WHERE event_date >= NOW() 
            ORDER BY event_date 
            LIMIT 5
            """,
            fetch=True
        )
        
        if not events:
            await message.answer(
                "На данный момент нет запланированных мероприятий. 🗓\n"
                "Попробуйте проверить позже или посмотрите спортивные объекты командой /find"
            )
            return
        
        response = ["<b>📅 Ближайшие спортивные мероприятия:</b>\n\n"]
        for event in events:
            date_str = event['event_date'].strftime("%d.%m.%Y в %H:%M")
            response.append(
                f"• <b>{event['title']}</b>\n"
                f"  🕒 {date_str}\n"
                f"  📍 {event['location']}\n"
                f"  ℹ️ {event['description']}\n\n"
            )
        
        await message.answer("".join(response))
    except Exception as e:
        logger.error(f"Error showing events: {e}")
        await message.answer(
            "Произошла ошибка при получении списка мероприятий. Пожалуйста, попробуйте позже."
        )

@router.message()
async def handle_free_text(message: types.Message):
    """Обработка свободных текстовых запросов"""
    user_query = message.text
    
    if len(user_query) < 5:
        await message.answer(
            "Пожалуйста, уточните ваш запрос или воспользуйтесь одной из команд:\n"
            "/find - поиск объектов\n"
            "/events - мероприятия\n"
            "/recommend - рекомендации"
        )
        return
    
    try:
        # Получаем контекст о пользователе
        user_data = await db.execute_query(
            """
            SELECT current_level, experience_points 
            FROM users 
            WHERE user_id = %s
            """,
            (message.from_user.id,),
            fetch=True
        )
        
        # Получаем информацию о спортивных объектах
        facilities = await db.execute_query(
            """
            SELECT name, type, sports, age_groups, address 
            FROM sports_facilities 
            ORDER BY RANDOM() 
            LIMIT 5
            """,
            fetch=True
        )
        
        # Получаем информацию о мероприятиях
        events = await db.execute_query(
            """
            SELECT title, description, event_date 
            FROM sport_events 
            WHERE event_date >= NOW() 
            ORDER BY event_date 
            LIMIT 3
            """,
            fetch=True
        )
        
        # Формируем контекст для AI
        context = (
            "Ты - спортивный помощник для жителей Сургута. "
            "Отвечай только на вопросы, связанные со спортом. "
            f"Уровень пользователя: {user_data[0]['current_level'] if user_data else 1}\n\n"
            "Спортивные объекты:\n"
        )
        
        for fac in facilities:
            context += (
                f"- {fac['name']} ({fac['type']}): {', '.join(fac['sports'])}, "
                f"адрес: {fac['address']}\n"
            )
        
        context += "\nМероприятия:\n"
        for event in events:
            date_str = event['event_date'].strftime("%d.%m.%Y")
            context += f"- {event['title']} ({date_str}): {event['description']}\n"
        
        context += (
            "\nБудь вежливым, кратким (3-5 предложений) и используй эмодзи. "
            "Если вопрос не по теме, вежливо сообщи, что можешь помочь только со спортивными вопросами."
        )
        
        # Получаем ответ от AI
        response = await mistral.generate_response(user_query, context)
        await message.answer(response)
    except Exception as e:
        logger.error(f"Error processing free text: {e}")
        await message.answer(
            "Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже."
        )

# ======================
# Запуск приложения
# ======================

async def on_startup():
    """Действия при запуске бота"""
    await db.connect()
    await db.init_db()
    
    # Добавляем тестовые данные
    await seed_test_data()
    
    logger.info("Bot started")

async def on_shutdown():
    """Действия при остановке бота"""
    await db.close()
    logger.info("Bot stopped")

async def seed_test_data():
    """Заполнение тестовыми данными"""
    try:
        # Проверяем, есть ли уже данные
        existing = await db.execute_query(
            "SELECT COUNT(*) FROM sports_facilities",
            fetch=True
        )
        
        if existing and existing[0][0] == 0:
            # Тестовые спортивные объекты
            test_facilities = [
                {
                    "name": "Спортивный комплекс 'Олимп'",
                    "type": "спортивный комплекс",
                    "address": "ул. Спортивная, 15",
                    "sports": ["плавание", "футбол", "баскетбол"],
                    "age_groups": ["дети", "подростки", "взрослые"],
                    "contacts": "+7 (3462) 123-456",
                    "description": "Крупнейший спортивный комплекс в центре города с бассейном и залами"
                },
                # ... другие объекты ...
            ]
            
            for fac in test_facilities:
                await db.execute_query(
                    """
                    INSERT INTO sports_facilities 
                    (name, type, address, sports, age_groups, contacts, description)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        fac["name"], fac["type"], fac["address"],
                        fac["sports"], fac["age_groups"],
                        fac["contacts"], fac["description"]
                    )
                )
            
            # Тестовые мероприятия
            test_events = [
                {
                    "title": "Открытый турнир по плаванию",
                    "description": "Ежегодный городской турнир по плаванию среди любителей",
                    "event_date": "2023-12-15 10:00:00",
                    "location": "Спортивный комплекс 'Олимп', бассейн"
                },
            ]
            
            for event in test_events:
                await db.execute_query(
                    """
                    INSERT INTO sport_events 
                    (title, description, event_date, location)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        event["title"], event["description"],
                        event["event_date"], event["location"]
                    )
                )
            
            logger.info("Test data seeded successfully")
    except Exception as e:
        logger.error(f"Error seeding test data: {e}")

async def main():
    await on_startup()
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
    


#nG2ac1xdGlnSHW2U7IEee6HADxcPf7fY -> api mistral
#5354843188:AAGw7HfazJXuxlruAMTYesFCHljTBahfHgk -> tg bot api