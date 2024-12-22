from flask import Flask, render_template, request
import requests
import json
import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

API_KEY = ""
LOCATION_URL = "http://dataservice.accuweather.com/locations/v1/cities/autocomplete"
FIVE_DAY_FORECAST_URL = "http://dataservice.accuweather.com/forecasts/v1/daily/5day/{}"
ONE_DAY_FORECAST_URL = "http://dataservice.accuweather.com/forecasts/v1/daily/1day/{}"

server = Flask(__name__)
app = dash.Dash(__name__, server=server, suppress_callback_exceptions=True)

# Кэш для хранения данных о погоде
weather_cache = {}

# Функция для получения координат города
def get_location_key(city_name):
    params = {
        "apikey": API_KEY,
        "q": city_name
    }
    try:
        response = requests.get(LOCATION_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data:
            location_key = data[0]["Key"]
            return location_key
        else:
            return None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к AccuWeather Location API: {e}")
        return None
    except (IndexError, KeyError) as e:
        print(f"Ошибка при обработке данных Location API: {e}")
        return None

def get_coordinates(location_key):
    url = f"http://dataservice.accuweather.com/locations/v1/{location_key}"
    params = {
        "apikey": API_KEY
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if data and "GeoPosition" in data:
            latitude = data["GeoPosition"]["Latitude"]
            longitude = data["GeoPosition"]["Longitude"]
            return latitude, longitude
        else:
            return None, None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к AccuWeather Location API (получение координат): {e}")
        return None, None
    except (IndexError, KeyError) as e:
        print(f"Ошибка при обработке данных Location API (получение координат): {e}")
        return None, None

# Функция для получения данных о погоде
def get_weather_data(location_key, days=1):
    cache_key = (location_key, days)
    if cache_key in weather_cache:
        return weather_cache[cache_key]

    if days == 1:
        url = ONE_DAY_FORECAST_URL.format(location_key)
    else:
        url = FIVE_DAY_FORECAST_URL.format(location_key)
    try:
        response = requests.get(url, params={"apikey": API_KEY, "metric": True, "details": True})
        response.raise_for_status()
        data = response.json()
        weather_cache[cache_key] = data
        return data
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к AccuWeather Forecast API: {e}")
        return None
    except (IndexError, KeyError) as e:
        print(f"Ошибка обработки данных Forecast API: {e}")
        return None

# Модель для оценки неблагоприятных погодных условий
def check_bad_weather(weather_data):
    if not weather_data or "DailyForecasts" not in weather_data:
        return "Нет данных о погоде"

    try:
        daily_forecasts = weather_data["DailyForecasts"]
        results = []
        for forecast in daily_forecasts:
            date = forecast["Date"][:10]  # Извлекаем дату
            temperature_max = forecast["Temperature"]["Maximum"]["Value"]
            temperature_min = forecast["Temperature"]["Minimum"]["Value"]
            wind_speed_day = forecast.get("Day", {}).get("Wind", {}).get("Speed", {}).get("Value", 0)
            wind_speed_night = forecast.get("Night", {}).get("Wind", {}).get("Speed", {}).get("Value", 0)
            precipitation_day = forecast.get("Day", {}).get("HasPrecipitation", False)
            precipitation_night = forecast.get("Night", {}).get("HasPrecipitation", False)

            if temperature_max > 30 or temperature_min < -5:
                results.append(f"{date}: Ой-ой, погода плохая (температура)")
            elif wind_speed_day > 10 or wind_speed_night > 10:
                results.append(f"{date}: Ой-ой, погода плохая (ветер)")
            elif precipitation_day or precipitation_night:
                results.append(f"{date}: Ой-ой, погода плохая (осадки)")
            else:
                results.append(f"{date}: Погода — супер")

        return results

    except KeyError as e:
        print(f"Ошибка: в данных о погоде нет ключа {e}: {weather_data}")
        return ["Недостаточно данных о погоде"] * len(daily_forecasts)

# Структура приложения
app.layout = html.Div([
    html.H1("Прогноз погоды для маршрута", style={'textAlign': 'center'}),
    html.Div([
        html.Div([
            html.Label("Начальный город:"),
            dcc.Input(id='start_city', type='text', required=True),
            html.Br(),
            html.Label("Конечный город:"),
            dcc.Input(id='end_city', type='text', required=True),
            html.Br(),
            html.Div(id='intermediate-cities'),
            html.Button('Добавить промежуточный город', id='add-city-btn', n_clicks=0),
            html.Br(),
            html.Label("Прогноз на:"),
            dcc.RadioItems(
                id='forecast_days',
                options=[
                    {'label': '1 день', 'value': 1},
                    {'label': '5 дней', 'value': 5}
                ],
                value=1,
                inline=True
            ),
            html.Br(),
            html.Button('Узнать погоду', id='submit-val', n_clicks=0),
        ], style={'width': '30%', 'display': 'inline-block', 'verticalAlign': 'top'}),
        html.Div([
            html.Label("Выберите тип данных:"),
            dcc.Dropdown(
                id='data-type-dropdown',
                options=[
                    {'label': 'Температура', 'value': 'temperature'},
                    {'label': 'Ветер', 'value': 'wind'},
                    {'label': 'Осадки', 'value': 'precipitation'}
                ],
                value='temperature'
            ),
            html.Br(),
            html.Label("Выберите город:"),
            dcc.RadioItems(
                id='city-select',
                options=[],
                value=''
            ),
        ], style={'width': '30%', 'display': 'inline-block', 'verticalAlign': 'top'}),
    ], style={'marginBottom': 25, 'marginTop': 25}),
    html.Div([
        html.Div(id='map-container', style={'width': '50%', 'display': 'inline-block'}),
        html.Div([
            dcc.Graph(id='weather-graph'),
            html.Div(id='weather-status')
        ], style={'width': '50%', 'display': 'inline-block'})
    ]),
    html.Div(id='weather-table')
])

# Коллбэк для добавления полей промежуточных городов
@app.callback(
    Output('intermediate-cities', 'children'),
    Input('add-city-btn', 'n_clicks'),
    State('intermediate-cities', 'children'),
    prevent_initial_call=True
)
def add_intermediate_city(n_clicks, children):
    if not children:
        children = []
    
    # Вставляем новый город в середину списка
    insert_index = len(children) // 2
    
    new_city_input = html.Div([
        dcc.Input(
            id={'type': 'intermediate_city', 'index': n_clicks},
            type='text',
            placeholder=f'Промежуточный город {len(children) + 1}',
        ),
        html.Br(),
    ])
    
    children.insert(insert_index, new_city_input)
    return children

# Коллбэк для обновления доступных городов
@app.callback(
    Output('city-select', 'options'),
    Output('city-select', 'value'),
    Input('submit-val', 'n_clicks'),
    State('start_city', 'value'),
    State('end_city', 'value'),
    State({'type': 'intermediate_city', 'index': dash.dependencies.ALL}, 'value')
)
def update_city_options(n_clicks, start_city, end_city, intermediate_cities):
    if n_clicks > 0:
        cities = [start_city, end_city] + (intermediate_cities or [])
        cities = [city for city in cities if city]
        cities = [city for i, city in enumerate(cities) if city not in cities[:i]]
        
        options = [{'label': city, 'value': city} for city in cities]
        return options, start_city if start_city else ''
    return [], ''

# Коллбэк для обработки запроса и вывода результатов
@app.callback(
    Output('weather-table', 'children'),
    Output('map-container', 'children'),
    Output('weather-graph', 'figure'),
    Output('weather-status', 'children'),
    Input('submit-val', 'n_clicks'),
    Input('data-type-dropdown', 'value'),
    Input('city-select', 'value'),
    Input('forecast_days', 'value'),
    State('start_city', 'value'),
    State('end_city', 'value'),
    State({'type': 'intermediate_city', 'index': dash.dependencies.ALL}, 'value')
)
def update_output(n_clicks, data_type, selected_city, forecast_days, start_city, end_city, intermediate_cities):
    if n_clicks > 0:
        cities = [start_city, end_city] + (intermediate_cities or [])
        cities = [city for city in cities if city]
        cities = [city for i, city in enumerate(cities) if city not in cities[:i]]

        if not cities:
            return "Пожалуйста, введите названия городов.", None, go.Figure(), None

        all_weather_data = {}
        all_weather_status = {}
        city_coordinates = {}

        for city in cities:
            location_key = get_location_key(city)
            if not location_key:
                return f"Не удалось определить местоположение города {city}.", None, go.Figure(), None

            latitude, longitude = get_coordinates(location_key)
            if latitude is None or longitude is None:
                return f"Не удалось получить координаты для города {city}.", None, go.Figure(), None

            weather_data = get_weather_data(location_key, days=forecast_days)
            all_weather_data[city] = weather_data
            all_weather_status[city] = check_bad_weather(weather_data)
            city_coordinates[city] = (latitude, longitude)

        table_data = []
        for city, weather_data in all_weather_data.items():
            if weather_data and 'DailyForecasts' in weather_data:
                for i, forecast in enumerate(weather_data['DailyForecasts']):
                    if i < forecast_days:
                        date = forecast["Date"][:10]
                        icon_number = forecast["Day"]["Icon"] if forecast_days > 1 else forecast["Day"]["Icon"]
                        icon_url = f"https://developer.accuweather.com/sites/default/files/{icon_number:02d}-s.png"
                        table_data.append({
                            'Город': city,
                            'Дата': date,
                            'День': i + 1,
                            'Макс. температура': forecast['Temperature']['Maximum']['Value'],
                            'Мин. температура': forecast['Temperature']['Minimum']['Value'],
                            'Скорость ветра днем (км/ч)': forecast['Day']['Wind']['Speed']['Value'] if forecast.get('Day', {}).get('Wind', {}).get('Speed', {}).get('Value') is not None else 'Нет данных',
                            'Скорость ветра ночью (км/ч)': forecast['Night']['Wind']['Speed']['Value'] if forecast.get('Night', {}).get('Wind', {}).get('Speed', {}).get('Value') is not None else 'Нет данных',
                            'Осадки днем': 'Есть' if forecast['Day']['HasPrecipitation'] else 'Нет',
                            'Осадки ночью': 'Есть' if forecast['Night']['HasPrecipitation'] else 'Нет',
                            'Иконка': icon_url
                        })
        
        table = dash_table.DataTable(
            columns=[
                {"name": i, "id": i} if i != 'Иконка' else {"name": i, "id": i, "presentation": "markdown"}
                for i in table_data[0].keys()
            ],
            data=[
                {
                    **d,
                    'Иконка': f'![{d["Город"]}]({d["Иконка"]})' if d['Иконка'] else ''
                } for d in table_data
            ],
            markdown_options={"html": True},
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'minWidth': '100px', 'width': '100px', 'maxWidth': '100px'},
            style_header={
                'backgroundColor': 'rgb(230, 230, 230)',
                'fontWeight': 'bold'
            }
        )

        # Создание карты
        fig_map = go.Figure()

        # Добавление маркеров для городов
        for city, (lat, lon) in city_coordinates.items():
            fig_map.add_trace(go.Scattermapbox(
                lat=[lat],
                lon=[lon],
                mode='markers',
                marker=go.scattermapbox.Marker(
                    size=14
                ),
                text=[city],
                name=city
            ))

        # Добавление линий маршрута
        lats = [coord[0] for coord in city_coordinates.values()]
        lons = [coord[1] for coord in city_coordinates.values()]
        fig_map.add_trace(go.Scattermapbox(
            lat=lats,
            lon=lons,
            mode='lines',
            line=dict(width=2, color='blue'),
            name='Маршрут'
        ))

        fig_map.update_layout(
            mapbox_style="open-street-map",
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
            mapbox=dict(
                center=dict(lat=sum(lats) / len(lats), lon=sum(lons) / len(lons)),
                zoom=4
            ),
            title='Карта маршрута'
        )

        map_component = dcc.Graph(figure=fig_map)

        # Если город не выбран, не строим график
        if not selected_city:
            return table, map_component, go.Figure(), None
        
        weather_data = all_weather_data.get(selected_city)
        weather_status = all_weather_status.get(selected_city)

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

        if data_type == 'temperature':
            fig.add_trace(go.Scatter(x=weather_df['Date'], y=weather_df['Temperature_Max'],
                         mode='lines+markers', name='Макс. температура'))
            fig.add_trace(go.Scatter(x=weather_df['Date'], y=weather_df['Temperature_Min'],
                         mode='lines+markers', name='Мин. температура'))
        elif data_type == 'wind':
            fig.add_trace(go.Scatter(x=weather_df['Date'], y=weather_df['Wind_Speed_Day'],
                         mode='lines+markers', name='Скорость ветра днем (км/ч)'))
            fig.add_trace(go.Scatter(x=weather_df['Date'], y=weather_df['Wind_Speed_Night'],
                         mode='lines+markers', name='Скорость ветра ночью (км/ч)'))
        elif data_type == 'precipitation':
            fig.add_trace(go.Bar(x=weather_df['Date'], y=weather_df['Precipitation_Night'].map({'Есть': 0, 'Нет': 1}),
                         name='Осадки ночью', marker_color='lightblue'))
            fig.add_trace(go.Bar(x=weather_df['Date'], y=weather_df['Precipitation_Day'].map({'Есть': 1, 'Нет': 0}),
                         name='Осадки днем', marker_color='blue'))
            fig.update_yaxes(
                tickmode='array',
                tickvals=[0, 1],
                ticktext=['Есть', 'Нет'],
                range=[0, 1.1] 
            )
            fig.update_layout(barmode='stack')

        fig.update_xaxes(title_text='Дата')
        fig.update_yaxes(title_text='Значение')
        fig.update_layout(title=f'Погода в {selected_city}', title_x=0.5)

        status_elements = [html.Li(status) for status in weather_status]

        return table, map_component, fig, html.Ul(children=status_elements)

    return "", None, go.Figure(), None

@server.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run_server(debug=True, port=8050)