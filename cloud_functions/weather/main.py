# ============================================================
# WEATHER CLOUD RUN FUNCTION (entry point: weather)
# ============================================================
#
# Triggered every day at 00:00 by Cloud Scheduler.
# Reads the cities from Cloud SQL, downloads the OpenWeather
# 5-day / 3-hour forecast for each one and appends it to the
# weather table.
#
# Secrets (password, openWeatherApi) come from Secret Manager
# as environment variables; the database host is an
# environment variable too, so nothing secret is in the code.
# ============================================================

import os
import requests

import pysqlite3
import sys

sys.modules["sqlite3"] = pysqlite3


import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

import functions_framework
from sqlalchemy import create_engine, URL



# Create the database connection once when the function starts
schema = "sql_cities_weather_flights"
host = os.getenv("cloud_sql_host")   # public IP of the Cloud SQL instance
user = "root"
password = os.getenv("password")
port = 3306

connection_url = URL.create(
    drivername="mysql+pymysql",
    username=user,
    password=password,
    host=host,
    port=port,
    database=schema
)

engine = create_engine(connection_url)


@functions_framework.http
def weather(request):
    """
    Get weather forecasts for Berlin, Hamburg and Munich
    and save them to the Cloud SQL weather table.
    """

    # Read cities from Cloud SQL
    cities_df = pd.read_sql(
        """
        SELECT
            city_id,
            city,
            latitude,
            longitude
        FROM cities
        WHERE city IN ('Berlin', 'Hamburg', 'Munich')
        """,
        con=engine
    )

    if cities_df.empty:
        return "No cities found in Cloud SQL.", 404

    # Get OpenWeather API key
    api_key = os.getenv("openWeatherApi")

    if not api_key:
        return "OpenWeather API key not found.", 500

    berlin_timezone = ZoneInfo("Europe/Berlin")
    weather_items = []

    # Call OpenWeather for each city
    for _, city in cities_df.iterrows():

        latitude = city["latitude"]
        longitude = city["longitude"]
        city_id = city["city_id"]
        city_name = city["city"]

        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={latitude}"
            f"&lon={longitude}"
            f"&appid={api_key}"
            "&units=metric"
        )

        response = requests.get(url, timeout=30)

        if response.status_code != 200:
            return (
                f"OpenWeather request failed for {city_name}: "
                f"{response.status_code}",
                500
            )

        weather_data = response.json()

        retrieval_time = datetime.now(
            berlin_timezone
        ).strftime("%Y-%m-%d %H:%M:%S")

        for item in weather_data["list"]:

            weather_items.append({
                "city_id": city_id,
                "city": city_name,
                "forecast_time": item.get("dt_txt"),
                "temperature": item["main"].get("temp"),
                "forecast": item["weather"][0].get("main"),
                "rain_in_last_3h": item.get("rain", {}).get("3h", 0),
                "wind_speed": item["wind"].get("speed"),
                "data_retrieved_at": retrieval_time
            })

    # Create DataFrame
    weather_df = pd.DataFrame(weather_items)

    weather_df["forecast_time"] = pd.to_datetime(
        weather_df["forecast_time"]
    )

    weather_df["data_retrieved_at"] = pd.to_datetime(
        weather_df["data_retrieved_at"]
    )

    # Save to Cloud SQL
    weather_df.to_sql(
        "weather",
        con=engine,
        if_exists="append",
        index=False
    )

    return f"Weather data successfully added: {len(weather_df)} rows"