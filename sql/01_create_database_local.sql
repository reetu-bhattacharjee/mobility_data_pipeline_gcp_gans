-- ============================================================
-- Gans data pipeline: database schema for the LOCAL MySQL server
-- Run once in MySQL Workbench (local connection) before 01_local_pipeline.ipynb
--
-- WARNING: the first line deletes the database and all its data.
-- Only run this on your LOCAL connection, never on the Cloud SQL one.
-- ============================================================

-- DROP DATABASE IF EXISTS sql_cities_weather_flights;  -- start clean while iterating on the design [Use only the first time]
CREATE DATABASE sql_cities_weather_flights;          -- same name locally and in the cloud, so the code only differs by host
USE sql_cities_weather_flights;

-- ------------------------------------------------------------
-- 1. cities: static facts about each city (filled by web scraping)
--    city_id is the key every other table uses; 
-- UNIQUE(city) lets the scraper re-run safely: an existing city is updated, never duplicated.
-- ------------------------------------------------------------
CREATE TABLE cities (
    city_id   INT AUTO_INCREMENT,
    city      VARCHAR(255) NOT NULL,
    country   VARCHAR(255) NOT NULL,
    latitude  FLOAT NOT NULL,          -- decimal degrees, used to query the weather and airport APIs
    longitude FLOAT NOT NULL,
    PRIMARY KEY (city_id),
    UNIQUE KEY uq_city (city)
);

-- ------------------------------------------------------------
-- 2. population: one row per city per collection date
--    Population changes over time, so we add rows instead of overwriting.
-- ------------------------------------------------------------
CREATE TABLE population (
    city_id              INT NOT NULL,
    population           INT NOT NULL,     -- head count, e.g. 3597000
    timestamp_population DATE NOT NULL,    -- the day the value was scraped
    PRIMARY KEY (city_id, timestamp_population),
    FOREIGN KEY (city_id) REFERENCES cities(city_id)
);

-- ------------------------------------------------------------
-- 3. weather: 5-day / 3-hour forecast snapshots (OpenWeather API)
--    Every pipeline run appends a new snapshot; data_retrieved_at tells them apart.
-- ------------------------------------------------------------
CREATE TABLE weather (
    weather_entry_id  INT AUTO_INCREMENT NOT NULL,
    city_id           INT NOT NULL,
    city              VARCHAR(255) NOT NULL,
    forecast_time     DATETIME NOT NULL,     -- the 3-hour slot being forecast (UTC)
    temperature       FLOAT,                 -- °C
    forecast          VARCHAR(55),           -- Clear / Clouds / Rain ...
    rain_in_last_3h   FLOAT,                 -- mm of rain in the slot, 0 if dry
    wind_speed        FLOAT,                 -- m/s
    data_retrieved_at DATETIME(6) NOT NULL,  -- when the forecast was downloaded (Berlin time)
    PRIMARY KEY (weather_entry_id),
    FOREIGN KEY (city_id) REFERENCES cities(city_id)
);

-- ------------------------------------------------------------
-- 4. airports: every airport we meet, near our cities or as a flight origin
-- ------------------------------------------------------------
CREATE TABLE airports (
    airport_icao VARCHAR(25) NOT NULL,       -- 4-letter ICAO code, e.g. EDDB = Berlin Brandenburg
    airport_name VARCHAR(255) NOT NULL,
    PRIMARY KEY (airport_icao)
);

-- ------------------------------------------------------------
-- 5. city_airports: link table (one city can be served by several airports)
-- ------------------------------------------------------------
CREATE TABLE city_airports (
    city_id      INT NOT NULL,
    city         VARCHAR(255) NOT NULL,
    airport_icao VARCHAR(25) NOT NULL,
    PRIMARY KEY (city_id, airport_icao),
    FOREIGN KEY (city_id)      REFERENCES cities(city_id),
    FOREIGN KEY (airport_icao) REFERENCES airports(airport_icao),
    INDEX idx_city_airports_airport (airport_icao)
);

-- ------------------------------------------------------------
-- 6. flights: tomorrow's scheduled arrivals (AeroDataBox API)
--    uq_flight stops the daily job from storing the same flight twice.
-- ------------------------------------------------------------
CREATE TABLE flights (
    flight_id      INT AUTO_INCREMENT NOT NULL,
    flight_num     VARCHAR(25) NOT NULL,     -- e.g. LH 1743
    departure_icao VARCHAR(25) NOT NULL,
    arrival_icao   VARCHAR(25) NOT NULL,
    arrival_time   DATETIME NOT NULL,        -- scheduled local arrival time
    PRIMARY KEY (flight_id),
    FOREIGN KEY (departure_icao) REFERENCES airports(airport_icao),
    FOREIGN KEY (arrival_icao)   REFERENCES airports(airport_icao),
    UNIQUE KEY uq_flight (flight_num, departure_icao, arrival_icao, arrival_time)
);
