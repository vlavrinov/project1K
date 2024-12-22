import logging
import os
from aiogram import Bot, Dispatcher, types, executor
from app import get_location_key, get_coordinates, get_weather_data, check_bad_weather
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
import plotly.graph_objects as go
import pandas as pd
import io

# Инициализация бота и диспетчера
bot = Bot(token="")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Структура для хранения данных о вводе пользователя
class Form(StatesGroup):
    start_city = State()
    end_city = State()
    intermediate_cities = State()
    add_more_cities = State()
    forecast_days = State()
    waiting_for_city = State()
    wants_graph = State()
    graph_type = State()
    selected_city_for_graph = State()

# Создание клавиатуры с основными командами
def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("Погода"))
    keyboard.add(types.KeyboardButton("Помощь"))
    return keyboard

# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    """
    Выводит приветственное сообщение и краткое описание возможностей бота.
    """
    await message.reply(
        "Привет! Я бот прогноза погоды. Я могу показать тебе погоду на 1 или 5 дней для начальной, конечной и промежуточных точек маршрута.\n"
        "Введи /help для просмотра доступных команд или нажми на кнопку",
        reply_markup=get_main_keyboard()
    )

# Обработчик команды /help или кнопки "Помощь"
@dp.message_handler(commands=['help'])
@dp.message_handler(lambda message: message.text == "Помощь")
async def cmd_help(message: types.Message):
    """
    Выводит список доступных команд и краткую инструкцию по использованию бота.
    """
    await message.reply(
        "Доступные команды:\n"
        "/start - начать работу с ботом\n"
        "/help - вывод справки\n"
        "/weather - запрос прогноза погоды\n"
        "Для запроса прогноза погоды введите /weather или нажмите кнопку 'Погода', а затем следуйте инструкциям бота.",
        reply_markup=get_main_keyboard()
    )

# Обработчик команды /weather или кнопки "Погода"
@dp.message_handler(commands=['weather'])
@dp.message_handler(lambda message: message.text == "Погода")
async def cmd_weather(message: types.Message, state: FSMContext):
    """
    Начинает процесс запроса прогноза погоды.
    """
    await Form.start_city.set()
    await message.reply("Введите начальный город:", reply_markup=types.ReplyKeyboardRemove())

# Обработчик ввода начального города
@dp.message_handler(state=Form.start_city)
async def process_start_city(message: types.Message, state: FSMContext):
    """
    Обрабатывает ввод начального города и запрашивает конечный город.
    """
    async with state.proxy() as data:
        data['start_city'] = message.text
    await Form.next()
    await message.reply("Введите конечный город:")

# Обработчик ввода конечного города
@dp.message_handler(state=Form.end_city)
async def process_end_city(message: types.Message, state: FSMContext):
    """
    Обрабатывает ввод конечного города и предлагает добавить промежуточные города.
    """
    async with state.proxy() as data:
        data['end_city'] = message.text
        data['intermediate_cities'] = []

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Да", callback_data="add_city"))
    keyboard.add(types.InlineKeyboardButton("Нет", callback_data="no_city"))

    await Form.add_more_cities.set()
    await message.reply("Хотите добавить промежуточные города?", reply_markup=keyboard)

# Обработчик нажатия кнопок при добавлении городов
@dp.callback_query_handler(lambda c: c.data in ['add_city', 'no_city'], state=Form.add_more_cities)
async def process_add_more_cities(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор пользователя: добавлять промежуточные города или нет.
    """
    await bot.answer_callback_query(callback_query.id)
    if callback_query.data == 'add_city':
        await Form.intermediate_cities.set()
        async with state.proxy() as data:
            if 'city_count' not in data:
              data['city_count'] = 1
            else:
              data['city_count'] += 1
            await bot.send_message(callback_query.from_user.id, f"Введите промежуточный город {data['city_count']}:")
    else:
        await Form.forecast_days.set()
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("1 день", callback_data="days_1"))
        keyboard.add(types.InlineKeyboardButton("5 дней", callback_data="days_5"))
        await bot.send_message(callback_query.from_user.id, "Выберите период прогноза:", reply_markup=keyboard)

# Обработчик ввода промежуточных городов
@dp.message_handler(state=Form.intermediate_cities)
async def process_intermediate_cities(message: types.Message, state: FSMContext):
    """
    Обрабатывает ввод промежуточных городов.
    """
    async with state.proxy() as data:
        data['intermediate_cities'].append(message.text)

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Да", callback_data="add_city"))
        keyboard.add(types.InlineKeyboardButton("Нет", callback_data="no_city"))

        await Form.add_more_cities.set()
        await message.reply("Хотите добавить еще один промежуточный город?", reply_markup=keyboard)

# Обработчик выбора периода прогноза
@dp.callback_query_handler(lambda c: c.data in ['days_1', 'days_5'], state=Form.forecast_days)
async def process_forecast_days(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор количества дней прогноза, предлагает построить график
    """
    await bot.answer_callback_query(callback_query.id)
    async with state.proxy() as data:
        data['forecast_days'] = int(callback_query.data.split('_')[1])

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Да", callback_data="graph_yes"))
        keyboard.add(types.InlineKeyboardButton("Нет", callback_data="graph_no"))
        await bot.send_message(callback_query.from_user.id, "Хотите построить график?", reply_markup=keyboard)

# Обработчик выбора "Хотите построить график?"
@dp.callback_query_handler(lambda c: c.data in ['graph_yes', 'graph_no'], state=Form.forecast_days)
async def process_wants_graph(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор пользователя: строить график или нет.
    """
    await bot.answer_callback_query(callback_query.id)
    async with state.proxy() as data:
      if callback_query.data == 'graph_yes':
          data['wants_graph'] = True
          cities = [data['start_city']] + data['intermediate_cities'] + [data['end_city']]
          keyboard = types.InlineKeyboardMarkup()
          for city in cities:
            keyboard.add(types.InlineKeyboardButton(city, callback_data=f"city_{city}"))

          await Form.selected_city_for_graph.set()
          await bot.send_message(callback_query.from_user.id, "Выберите город для которого нужно построить график:", reply_markup=keyboard)
      else:
          data['wants_graph'] = False
          await send_weather_forecast(callback_query.from_user.id, state)
          await state.finish()

@dp.callback_query_handler(lambda c: c.data.startswith('city_'), state=Form.selected_city_for_graph)
async def process_select_city_for_graph(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор пользователя города для построения графика
    """
    await bot.answer_callback_query(callback_query.id)
    async with state.proxy() as data:
      data['selected_city_for_graph'] = callback_query.data.split('city_')[1]

      keyboard = types.InlineKeyboardMarkup()
      keyboard.add(types.InlineKeyboardButton("Температура", callback_data="graph_temperature"))
      keyboard.add(types.InlineKeyboardButton("Ветер", callback_data="graph_wind"))
      keyboard.add(types.InlineKeyboardButton("Осадки", callback_data="graph_precipitation"))

      await Form.graph_type.set()
      await bot.send_message(callback_query.from_user.id, "Выберите тип графика:", reply_markup=keyboard)

# Обработчик выбора типа графика
@dp.callback_query_handler(lambda c: c.data.startswith('graph_'), state=Form.graph_type)
async def process_graph_type(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Обрабатывает выбор типа графика и отправляет график пользователю.
    """
    await bot.answer_callback_query(callback_query.id)
    async with state.proxy() as data:
        data['graph_type'] = callback_query.data.split('_')[1]
        await send_weather_forecast(callback_query.from_user.id, state) # Эта строка удалена из функции и добавлена сюда

        if data['wants_graph']:
          city = data['selected_city_for_graph']
          forecast_days = data['forecast_days']
          graph_type = data['graph_type']

          location_key = get_location_key(city)
          if location_key:
              weather_data = get_weather_data(location_key, days=forecast_days)
              if weather_data:
                # Подготовка данных для графиков
                weather_df = pd.DataFrame(weather_data['DailyForecasts'][:forecast_days])
                # Добавляем даты на графики
                weather_df['Date'] = pd.to_datetime(weather_df['Date']).dt.strftime('%Y-%m-%d')

                # Преобразование данных о температуре
                weather_df['Temperature_Max'] = weather_df['Temperature'].apply(lambda x: x['Maximum']['Value'])
                weather_df['Temperature_Min'] = weather_df['Temperature'].apply(lambda x: x['Minimum']['Value'])

                # Преобразование данных о скорости ветра
                weather_df['Wind_Speed_Day'] = weather_df['Day'].apply(lambda x: x['Wind']['Speed']['Value'])
                weather_df['Wind_Speed_Night'] = weather_df['Night'].apply(lambda x: x['Wind']['Speed']['Value'])

                # Преобразование данных об осадках
                weather_df['Precipitation_Day'] = weather_df['Day'].apply(lambda x: 'Есть' if x['HasPrecipitation'] else 'Нет')
                weather_df['Precipitation_Night'] = weather_df['Night'].apply(lambda x: 'Есть' if x['HasPrecipitation'] else 'Нет')

                fig = go.Figure()

                if graph_type == 'temperature':
                    fig.add_trace(go.Scatter(x=weather_df['Date'], y=weather_df['Temperature_Max'],
                                mode='lines+markers', name='Макс. температура'))
                    fig.add_trace(go.Scatter(x=weather_df['Date'], y=weather_df['Temperature_Min'],
                                mode='lines+markers', name='Мин. температура'))
                elif graph_type == 'wind':
                    fig.add_trace(go.Scatter(x=weather_df['Date'], y=weather_df['Wind_Speed_Day'],
                                mode='lines+markers', name='Скорость ветра днем'))
                    fig.add_trace(go.Scatter(x=weather_df['Date'], y=weather_df['Wind_Speed_Night'],
                                mode='lines+markers', name='Скорость ветра ночью'))
                elif graph_type == 'precipitation':
                    fig.add_trace(go.Bar(x=weather_df['Date'], y=weather_df['Precipitation_Day'].map({'Есть': 1, 'Нет': 0}),
                                name='Осадки днем', marker_color='blue'))
                    fig.add_trace(go.Bar(x=weather_df['Date'], y=weather_df['Precipitation_Night'].map({'Есть': 0, 'Нет': 1}),
                                name='Осадки ночью', marker_color='lightblue'))
                    fig.update_yaxes(
                      tickmode='array',
                      tickvals=[0, 1],
                      ticktext=['Есть', 'Нет'],
                      range=[0, 1.1]
                    )
                    fig.update_layout(barmode='stack')

                fig.update_xaxes(title_text='Дата')
                fig.update_yaxes(title_text='Значение')
                fig.update_layout(title=f'Погода в {city}', title_x=0.5)

                # Отправка графика в виде изображения
                img_bytes = fig.to_image(format="png")
                await bot.send_photo(callback_query.from_user.id, photo=io.BytesIO(img_bytes))
              else:
                await bot.send_message(callback_query.from_user.id, f"Не удалось получить данные о погоде для города {city}.")
          else:
            await bot.send_message(callback_query.from_user.id, f"Не удалось определить местоположение для города {city}.")
    await state.finish()

# Функция для отправки прогноза погоды
async def send_weather_forecast(chat_id, state: FSMContext):
    """
    Отправляет прогноз погоды пользователю.
    """
    async with state.proxy() as data:
        cities = [data['start_city']] + data['intermediate_cities'] + [data['end_city']]
        forecast_days = data['forecast_days']
        forecast_message = ""

        for city in cities:
            location_key = get_location_key(city)
            if not location_key:
                forecast_message += f"Не удалось определить местоположение для города {city}.\n"
                continue

            weather_data = get_weather_data(location_key, days=forecast_days)
            if not weather_data:
                forecast_message += f"Не удалось получить прогноз погоды для города {city}.\n"
                continue

            weather_results = check_bad_weather(weather_data)
            forecast_message += f"Прогноз погоды для города {city} на {forecast_days} дней:\n"
            for i, result in enumerate(weather_results):
                if i < forecast_days:
                    forecast_message += f"- {result}\n"

            # Добавляем данные о температуре, скорости ветра и осадках, если они доступны
            if weather_data and 'DailyForecasts' in weather_data:
                for i, forecast in enumerate(weather_data['DailyForecasts']):
                    if i < forecast_days:
                        date = forecast["Date"][:10]
                        temp_max = forecast['Temperature']['Maximum']['Value']
                        temp_min = forecast['Temperature']['Minimum']['Value']
                        wind_speed_day = forecast.get("Day", {}).get("Wind", {}).get("Speed", {}).get("Value", "N/A")
                        wind_speed_night = forecast.get("Night", {}).get("Wind", {}).get("Speed", {}).get("Value", "N/A")
                        precipitation_day = "Есть" if forecast.get("Day", {}).get("HasPrecipitation") else "Нет"
                        precipitation_night = "Есть" if forecast.get("Night", {}).get("HasPrecipitation") else "Нет"

                        forecast_message += f"  {date}:\n"
                        forecast_message += f"    - Температура: днем {temp_max}°C, ночью {temp_min}°C\n"
                        forecast_message += f"    - Ветер: днем {wind_speed_day} км/ч, ночью {wind_speed_night} км/ч\n"
                        forecast_message += f"    - Осадки: днем {precipitation_day}, ночью {precipitation_night}\n"

            # Добавляем ссылку на AccuWeather
            if weather_data and 'DailyForecasts' in weather_data:
                link = weather_data['DailyForecasts'][0]['MobileLink']
                forecast_message += f"Подробнее: {link}\n"

            # Разделение сообщения на части, если оно слишком длинное
            max_message_length = 4096
            if len(forecast_message) > max_message_length:
              for i in range(0, len(forecast_message), max_message_length):
                await bot.send_message(chat_id, forecast_message[i:i + max_message_length], reply_markup=get_main_keyboard())
              forecast_message = ""
        
        if forecast_message != "":
          await bot.send_message(chat_id, forecast_message, reply_markup=get_main_keyboard())

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)