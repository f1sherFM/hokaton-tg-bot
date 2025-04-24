import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    CallbackContext
)
from database import Database
import requests
import json
from config import TELEGRAM_TOKEN, MISTRAL_API_KEY, MISTRAL_API_URL

# Инициализация базы данных
db = Database()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Обработчики команд
async def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    
    await update.message.reply_text(
        f"🏆 Привет, {user.first_name}!\n\n"
        "Я - бот спортивной инфраструктуры Сургута.\n"
        "Я помогу тебе найти спортивные объекты и секции в нашем городе.\n\n"
        "Вот что я умею:\n"
        "/facilities - поиск спортивных объектов\n"
        "/sections - поиск спортивных секций\n"
        "/ask - задать вопрос о спорте в Сургуте\n\n"
        "Выбери нужную команду из меню или напиши /help для справки."
    )

async def help_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "📋 Доступные команды:\n\n"
        "/start - начать работу с ботом\n"
        "/facilities - поиск спортивных объектов\n"
        "/sections - поиск спортивных секций\n"
        "/ask - задать вопрос о спорте в Сургуте\n\n"
        "Просто выбери нужную команду из меню!"
    )

async def facilities_command(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [
            InlineKeyboardButton("Все объекты", callback_data='facility_all'),
            InlineKeyboardButton("Стадионы", callback_data='facility_stadium'),
        ],
        [
            InlineKeyboardButton("Бассейны", callback_data='facility_pool'),
            InlineKeyboardButton("Скейт-парки", callback_data='facility_skatepark'),
        ],
        [
            InlineKeyboardButton("Скалодромы", callback_data='facility_climbing'),
            InlineKeyboardButton("Тренажерные залы", callback_data='facility_gym'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('🏟 Выберите тип спортивного объекта:', reply_markup=reply_markup)

async def sections_command(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [
            InlineKeyboardButton("Все секции", callback_data='section_all'),
            InlineKeyboardButton("Для детей", callback_data='section_children'),
        ],
        [
            InlineKeyboardButton("Для взрослых", callback_data='section_adults'),
            InlineKeyboardButton("Футбол", callback_data='sport_football'),
        ],
        [
            InlineKeyboardButton("Хоккей", callback_data='sport_hockey'),
            InlineKeyboardButton("Плавание", callback_data='sport_swimming'),
        ],
        [
            InlineKeyboardButton("Единоборства", callback_data='sport_martial'),
            InlineKeyboardButton("Йога", callback_data='sport_yoga'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('🏅 Выберите критерии поиска секций:', reply_markup=reply_markup)

async def ask_question(update: Update, context: CallbackContext) -> None:
    question = ' '.join(context.args)
    if not question:
        await update.message.reply_text("Пожалуйста, задайте вопрос после команды /ask")
        return
    
    await update.message.reply_text("🔍 Ищу информацию...")
    
    try:
        headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "mistral-tiny",
            "messages": [
                {
                    "role": "system",
                    "content": "Ты помощник по спортивной инфраструктуре города Сургут. "
                               "Отвечай кратко и информативно только по теме спорта в Сургуте."
                },
                {
                    "role": "user",
                    "content": question
                }
            ]
        }
        
        response = requests.post(MISTRAL_API_URL, headers=headers, json=data)
        response.raise_for_status()
        answer = response.json()['choices'][0]['message']['content']
        await update.message.reply_text(answer)
    except Exception as e:
        logger.error(f"Ошибка Mistral API: {e}")
        await update.message.reply_text("⚠️ Извините, не могу обработать ваш запрос сейчас. Попробуйте позже.")

# Обработчики кнопок
async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    
    if data[0] == 'facility':
        await handle_facility_query(query, data[1])
    elif data[0] == 'section' or data[0] == 'sport':
        await handle_section_query(query, data)

async def handle_facility_query(query, facility_type):
    type_names = {
        'all': 'все',
        'stadium': 'стадион',
        'pool': 'бассейн',
        'skatepark': 'скейт-парк',
        'climbing': 'скалодром',
        'gym': 'тренажерный зал'
    }
    
    facilities = db.get_facilities(type_names[facility_type] if facility_type != 'all' else None)
    
    if not facilities:
        await query.edit_message_text(text="❌ Нет объектов такого типа.")
        return
    
    message = f"🏟 <b>Спортивные объекты ({type_names[facility_type]}):</b>\n\n"
    for facility in facilities:
        message += (
            f"<b>{facility['name']}</b> ({facility['type']})\n"
            f"📍 Адрес: {facility['address']}\n"
            f"📞 Телефон: {facility['phone'] or 'не указан'}\n\n"
        )
    
    await query.edit_message_text(text=message, parse_mode='HTML')

async def handle_section_query(query, data):
    if data[0] == 'section':
        age_group = None
        if data[1] == 'children':
            age_group = 'дети'
        elif data[1] == 'adults':
            age_group = 'взрослые'
        
        sections = db.get_sections(age_group=age_group)
        title = f"Спортивные секции ({'для ' + age_group if age_group else 'все'}):"
    else:
        sport_type = {
            'football': 'футбол',
            'hockey': 'хоккей',
            'swimming': 'плавание',
            'martial': 'единоборства',
            'yoga': 'йога'
        }[data[1]]
        
        sections = db.get_sections(sport_type=sport_type)
        title = f"Спортивные секции ({sport_type}):"
    
    if not sections:
        await query.edit_message_text(text="❌ Нет секций по выбранным критериям.")
        return
    
    message = f"🏅 <b>{title}</b>\n\n"
    for section in sections:
        message += (
            f"<b>{section['sport_type'].capitalize()}</b> ({section['age_group']})\n"
            f"🏢 {section['facility_name']}\n"
            f"📍 {section['address']}\n"
            f"⏰ Расписание: {section['schedule']}\n"
            f"💵 Стоимость: {section['price'] or 'бесплатно'}\n\n"
        )
    
    await query.edit_message_text(text=message, parse_mode='HTML')

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("facilities", facilities_command))
    application.add_handler(CommandHandler("sections", sections_command))
    application.add_handler(CommandHandler("ask", ask_question))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()