"""Gans daily pipeline: Google Cloud Run function (Python), triggered by Cloud Scheduler.

Every run:
  1. reads the static tables (cities, city_airports) from Cloud SQL,
  2. downloads the 5-day weather forecast for every city -> appends to `weather`,
  3. downloads tomorrow's arrivals for every airport     -> inserts into `airports` + `flights`.

Entry point: update_weather_and_flights
Secrets come from the function's runtime environment variables (never hard-coded):
  DB_PASSWORD, DB_HOST, OPENWEATHER_API_KEY, AERODATABOX_API_KEY
"""

# Swap the built-in sqlite3 for pysqlite3, as in the course's Cloud Function template.
# This pipeline only talks to MySQL, so it is a harmless safeguard rather than a requirement.
import pysqlite3
import sys
sys.modules["sqlite3"] = pysqlite3

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import functions_framework
import pandas as pd
import requests
from sqlalchemy import URL, create_engine, text

SCHEMA = "sql_cities_weather_flights"
BERLIN_TZ = ZoneInfo("Europe/Berlin")


# ----------------------------------------------------------------------------------------
# HTTP entry point: Cloud Scheduler calls the function URL, this function runs
# ----------------------------------------------------------------------------------------
@functions_framework.http
def update_weather_and_flights(request):
    engine = get_engine()

    cities_df = pd.read_sql("SELECT city_id, city, latitude, longitude FROM cities", con=engine)
    icao_codes = pd.read_sql("SELECT DISTINCT airport_icao FROM city_airports", con=engine)["airport_icao"].tolist()

    weather_df = get_weather_forecast(cities_df, os.environ["OPENWEATHER_API_KEY"])
    if not weather_df.empty:
        weather_df.to_sql("weather", con=engine, if_exists="append", index=False)

    arrivals_df = tomorrows_flight_arrivals(icao_codes, os.environ["AERODATABOX_API_KEY"])
    save_flights(arrivals_df, engine)

    return f"Weather rows added: {len(weather_df)} | arrivals stored: {len(arrivals_df)}"


def get_engine():
    """SQLAlchemy engine for the Cloud SQL instance (URL.create escapes special characters in the password)."""
    url = URL.create(
        drivername="mysql+pymysql",
        username="root",
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],    # public IP of the Cloud SQL instance
        port=3306,
        database=SCHEMA,
    )
    return create_engine(url)


def get_weather_forecast(cities_df, api_key):
    """5-day / 3-hour OpenWeather forecast for every city, as a DataFrame shaped like the `weather` table."""
    rows = []
    retrieved_at = datetime.now(BERLIN_TZ).replace(tzinfo=None)

    for city in cities_df.to_dict("records"):
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"lat": city["latitude"], "lon": city["longitude"], "appid": api_key, "units": "metric"},
            timeout=30,
        )
        response.raise_for_status()

        for slot in response.json()["list"]:
            rows.append({
                "city_id": city["city_id"],
                "city": city["city"],
                "forecast_time": slot["dt_txt"],
                "temperature": slot["main"].get("temp"),
                "forecast": slot["weather"][0].get("main"),
                "rain_in_last_3h": slot.get("rain", {}).get("3h", 0),
                "wind_speed": slot["wind"].get("speed"),
                "data_retrieved_at": retrieved_at,
            })

    if not rows:
        return pd.DataFrame(rows)
    weather_df = pd.DataFrame(rows)
    weather_df["forecast_time"] = pd.to_datetime(weather_df["forecast_time"])
    return weather_df


def tomorrows_flight_arrivals(icao_list, api_key):
    """Tomorrow's scheduled passenger arrivals for each airport (two 12-hour calls per airport)."""
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"}
    tomorrow = datetime.now(BERLIN_TZ).date() + timedelta(days=1)
    rows = []

    for icao in icao_list:
        for start, end in [("00:00", "11:59"), ("12:00", "23:59")]:
            response = requests.get(
                f"https://aerodatabox.p.rapidapi.com/flights/airports/icao/{icao}/{tomorrow}T{start}/{tomorrow}T{end}",
                headers=headers,
                params={"direction": "Arrival", "withLeg": "true", "withCancelled": "false",
                        "withCodeshared": "false", "withCargo": "false", "withPrivate": "false",
                        "withLocation": "false"},
                timeout=30,
            )
            if response.status_code != 200:   # e.g. 204 for the closed Berlin-Tegel airport
                continue

            for flight in response.json().get("arrivals") or []:
                departure_airport = (flight.get("departure") or {}).get("airport") or {}
                scheduled = ((flight.get("arrival") or {}).get("scheduledTime") or {}).get("local")
                if not (flight.get("number") and scheduled and departure_airport.get("icao")):
                    continue
                rows.append({
                    "flight_num": flight["number"],
                    "departure_icao": departure_airport["icao"],
                    "departure_airport_name": (departure_airport.get("name") or departure_airport.get("municipalityName")
                                               or departure_airport["icao"]),   # never empty -> FK never fails
                    "arrival_icao": icao,
                    "arrival_time": scheduled[:16],   # "2026-10-02 06:15+02:00" -> local time without offset
                })

    arrivals_df = pd.DataFrame(rows)
    if arrivals_df.empty:
        return arrivals_df

    arrivals_df["arrival_time"] = pd.to_datetime(arrivals_df["arrival_time"], errors="coerce")
    arrivals_df = arrivals_df.dropna(subset=["arrival_time"])
    return (arrivals_df[arrivals_df["arrival_time"].dt.date == tomorrow]
            .drop_duplicates(subset=["flight_num", "departure_icao", "arrival_icao", "arrival_time"]))


def save_flights(arrivals_df, engine):
    """Insert unseen departure airports first (foreign key), then the flights; re-runs never duplicate."""
    if arrivals_df.empty:
        return

    airports = (arrivals_df[["departure_icao", "departure_airport_name"]]
                .drop_duplicates(subset=["departure_icao"]))

    with engine.begin() as connection:
        for row in airports.to_dict("records"):
            # INSERT IGNORE keeps the nicer names already stored for our own airports
            connection.execute(text("""
                INSERT IGNORE INTO airports (airport_icao, airport_name)
                VALUES (:icao, :name)
            """), {"icao": row["departure_icao"], "name": row["departure_airport_name"]})

        for row in arrivals_df.to_dict("records"):
            connection.execute(text("""
                INSERT IGNORE INTO flights (flight_num, departure_icao, arrival_icao, arrival_time)
                VALUES (:flight_num, :departure_icao, :arrival_icao, :arrival_time)
            """), {k: row[k] for k in ("flight_num", "departure_icao", "arrival_icao", "arrival_time")})
