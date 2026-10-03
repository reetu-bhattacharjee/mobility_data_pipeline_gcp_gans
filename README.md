# Automated Cloud Data Pipeline for E-Scooter Demand: Weather and Flight Data on Google Cloud

*A data engineering case study for **Gans**, an e-scooter-sharing start-up, built during the WBS Coding School Data Science bootcamp.*

---

## 🎯 Project Overview

An e-scooter company makes money only when a scooter is standing where someone wants to ride it. Gans' scooters drift: people ride uphill and walk down, commute into the centre each morning, give up when it rains, and land at the airport with a backpack looking for a ride into town. To move scooters *before* demand appears, Gans first needs data on those patterns, collected automatically every day.

I built that data foundation: a pipeline that **scrapes city data from Wikipedia, pulls weather forecasts and flight arrivals from two APIs, and stores everything in a relational MySQL database on Google Cloud**. A serverless Cloud Function runs it every day on a schedule, with no laptop involved.

The result: **one daily, query-ready view of the 5-day weather and tomorrow's ~980 arriving flights across Berlin, Hamburg and Munich.**

---

## 🧭 The story of the data

I'm writing this the way I'd explain it to a new colleague, because the *why* behind each table matters more than the code.

### Chapter 1: Where are we? (cities and population)

Everything starts with geography. Gans launches in three German cities. Every later API call needs a **latitude and longitude**, so the first job was to scrape each city's Wikipedia page for its country, coordinates and population.

Wikipedia was a deliberate choice over a downloaded CSV. A CSV is out of date the day you download it, while Wikipedia is kept current by thousands of editors. All three city pages share the same infobox layout, so **one loop and one function** handle every city, and adding Paris or Vienna later is a one-word change.

| City | Population (scraped 30 Sep 2026) | Coordinates |
|---|---:|---|
| Berlin | 3,597,000 | 52.52 N, 13.41 E |
| Hamburg | 1,973,900 | 53.55 N, 10.00 E |
| Munich | 1,505,040 | 48.14 N, 11.58 E |

One design decision I'm proud of: **population lives in its own table, with a date.** A city's coordinates never change, but its population does. Instead of overwriting the number every year, each scrape adds a row, so the history builds itself.

### Chapter 2: Will people want to ride? (weather)

Rain kills scooter demand. Using each city's coordinates from the database, the pipeline calls the **OpenWeather 5-day / 3-hour forecast** and keeps only what a demand model would use: temperature, the main condition (Clear, Clouds, Rain…), rain volume and wind speed.

That's **40 forecast slots per city, 120 rows per run**. In the first snapshot (1 Oct 2026), the next five days looked mostly cloudy, with one light shower forecast over Berlin on the morning of 2 Oct (0.47 mm). It's exactly the kind of small signal an operations team could act on.

Every run is **appended, not replaced**, and stamped with `data_retrieved_at`. Over time this becomes a record of *what we thought the weather would be* versus *what it was*, which is valuable once Gans starts modelling.

### Chapter 3: Who is arriving? (airports and flights)

Young tourists on cheap flights are a target group for Gans. They arrive with a backpack and no car, and they need a scooter near the city centre. So the question became: *how many planes land in each city tomorrow, and when?*

First, the **AeroDataBox API** found the airports within 50 km of each city, which gave 4 airports. Berlin had a surprise: the API still lists **Tegel (EDDT)**, which closed in 2020 and now returns an empty response. Real-world data is never as tidy as the documentation suggests.

Then, for each airport, the pipeline downloads **tomorrow's scheduled passenger arrivals**. Cancelled flights, cargo, private jets and codeshare duplicates are filtered out, so one physical plane counts once. A single run for 2 Oct 2026 returned:

| Airport | Arrivals (00:00–11:59) | Arrivals (12:00–23:59) | Total |
|---|---:|---:|---:|
| Munich (EDDM) | 181 | 318 | 499 |
| Berlin Brandenburg (EDDB) | 95 | 208 | 303 |
| Hamburg (EDDH) | 53 | 131 | 184 |
| **All** | **329** | **657** | **982 after de-duplication** |

Two things stood out to me straight away, and three days of data (30 Sep, 2 Oct and 3 Oct) confirmed that neither was a one-day fluke:

- **Munich receives about half of all arrivals but has the smallest population of the three.** Per resident, Munich gets roughly 4× the air traffic of Berlin (on average ≈318 vs ≈76 daily arrivals per million inhabitants). If tourists are the target, Munich's airport rail links and centre may deserve a bigger share of the fleet than its population suggests.
- **Two out of every three flights land after midday** (63–67% on each of the three days). Airport-driven demand builds through the afternoon and evening, so a rebalancing truck run in the late morning fits that pattern better than one at dawn.

![Arrivals per city per day](images/chart_arrivals_per_city.png)
*Munich leads on every collected day; Hamburg, despite having more residents than Munich, gets about a third of its flights.*

![Arrivals per million residents](images/chart_arrivals_per_resident.png)
*Normalised by population, the gap becomes dramatic: Munich is an air-travel magnet far beyond its size.*

![Morning vs afternoon arrivals](images/chart_morning_vs_afternoon.png)
*The afternoon wave is stable from day to day, which makes it something an operations team can actually plan around.*

The flights came from **196 different departure airports**, from Istanbul and Izmir to Bangkok and Singapore. Each one was added to the `airports` table so every flight can be traced to its origin.

### Chapter 4: Making it run without me (the cloud)

A pipeline you have to run by hand isn't really a pipeline. So I moved it to **Google Cloud Platform**:

1. **Cloud SQL (MySQL 8.0)**: the same schema as my local database, now reachable by anyone in the company.
2. **Two Cloud Run functions (Python 3.14, europe-west1)**: `weather` and `flights`, each packaged as its own serverless function. No server to maintain, it costs nothing while idle, and if the flight API has a bad day, the weather still gets collected.
3. **Secret Manager**: the database password and API keys never appear in the code. Google hands them to the functions as environment variables at run time.
4. **Cloud Scheduler**: two cron jobs (`0 0 * * *`) call the functions every night at 00:00, so tomorrow's flights and the fresh forecast are waiting in the database before anyone at Gans has had breakfast.

Static data (cities and airports) is loaded once from the notebook. Dynamic data (weather and flights) refreshes itself daily.

---

## 🏗️ Architecture

![How the Gans pipeline runs](images/architecture.png)

## 🗄️ Data model

![The Gans database: six connected tables](images/data_model.png)

Primary keys, foreign keys and unique constraints let **the database itself refuse bad data**. A flight can't point to an unknown airport, and running the job twice can't store the same flight twice (`UNIQUE (flight_num, departure_icao, arrival_icao, arrival_time)`).

---

## 📊 Data sources

| Source | What I took | How | Volume per run |
|---|---|---|---|
| [Wikipedia](https://en.wikipedia.org/wiki/Berlin) | country, coordinates, population | BeautifulSoup web scraping | 3 cities |
| [OpenWeather 5-day forecast](https://openweathermap.org/forecast5) | temperature, condition, rain, wind | REST API (free key) | 120 rows (40 × 3 cities) |
| [AeroDataBox on RapidAPI](https://rapidapi.com/aedbx-aedbx/api/aerodatabox) | nearby airports, tomorrow's arrivals | REST API (RapidAPI key) | ~930–980 flights |

---

## 🧗 Challenges and what they taught me

- **A password that broke the connection string.** My Cloud SQL password contained special characters, which a hand-written `mysql+pymysql://user:password@host` URL mistakes for URL syntax. The fix was `sqlalchemy.URL.create(...)`, which escapes everything properly. Lesson: never build credentials into strings by hand.
- **"It worked in my notebook."** Notebooks remember variables from cells you ran an hour ago. Code that seemed fine failed in a clean environment because it relied on a `.env` loaded three cells earlier. Now every notebook loads its own secrets at the top and runs top to bottom.
- **The 12-hour API window.** AeroDataBox's schedule endpoint accepts at most 12 hours per request, so a full day is two calls per airport.
- **Time zones.** The API returns times like `2026-10-02 06:15+02:00`, but MySQL `DATETIME` has no offset. I store local arrival time (what matters to a scooter on the street) and compute "tomorrow" in Berlin time, not UTC.
- **Idempotency.** A daily job *will* run twice one day. `ON DUPLICATE KEY UPDATE`, `INSERT IGNORE` and unique keys mean a re-run updates rows or skips them, instead of duplicating them or crashing.
- **Insertion order.** `flights` references `airports`, so a flight from Singapore can only be stored after Singapore's airport exists. The code writes parents before children: airports, then city–airport links, then flights.
- **The weather function that changed its mind.** The first time I deployed the weather function, it failed with code I knew was correct. A little later, without a single change, it simply started working. My best explanation: when a function is connected to Secret Manager, the permission to read the secrets takes a few minutes to become active, so the first run most likely started without its password. Lesson: in the cloud, "it doesn't work" sometimes means "not yet". Read the logs before rewriting the code.

---

## 🛠️ Technologies used

- **Language:** Python 3.14 (Cloud Run runtime), SQL (MySQL 8.0)
- **Libraries:** pandas, requests, BeautifulSoup4, SQLAlchemy, PyMySQL, lat-lon-parser, python-dotenv, functions-framework
- **Cloud (europe-west1):** Google Cloud SQL, Google Cloud Run functions, Google Cloud Scheduler, Google Secret Manager
- **Tools:** Jupyter Notebook, MySQL Workbench, RapidAPI

---

## 📁 Project structure

```
mobility_data_pipeline_gcp_gans/
├── README.md                          # you are here
├── requirements.txt                   # libraries for the notebooks
├── .env.example                       # names of the secrets needed (no real values)
├── .gitignore                         # keeps .env and clutter out of git
├── data/                              # small, real outputs of the pipeline (safe to share)
│   ├── arrivals_by_airport.csv        # arrivals per airport and half-day, 3 collection days
│   ├── pipeline_runs.csv              # each run: API-reported vs stored flights
│   └── city_population.csv            # scraped from Wikipedia on 30 Sep 2026
├── images/                            # charts used in this README
├── notebooks/
│   ├── 01_local_pipeline.ipynb        # Phase 1: full pipeline into local MySQL
│   └── 02_cloud_pipeline.ipynb        # Phase 2: same pipeline into Google Cloud SQL
├── sql/
│   ├── 01_create_database_local.sql   # schema for local MySQL (drops and recreates)
│   └── 02_create_database_cloud.sql   # schema for Cloud SQL (never drops data)
└── cloud_functions/
    ├── weather/
    │   ├── main.py                    # daily forecast job (entry point: weather)
    │   └── requirements.txt           # libraries installed by Cloud Run
    └── flights/
        ├── main.py                    # daily airports + tomorrow's arrivals job (entry point: flights)
        └── requirements.txt
```

---

## 🔗 How to reproduce it

1. **Get the keys:** a free [OpenWeather](https://home.openweathermap.org/users/sign_up) API key and an [AeroDataBox](https://rapidapi.com/aedbx-aedbx/api/aerodatabox) key on RapidAPI.
2. **Secrets:** copy `.env.example` to a file named `.env` in the repository folder or any folder above it, and fill it in. The notebooks find it automatically, and `.gitignore` keeps it out of git.
3. **Local run:** `python -m pip install -r requirements.txt`, run `sql/01_create_database_local.sql` in MySQL Workbench, then run `notebooks/01_local_pipeline.ipynb` top to bottom.
4. **Cloud database:** create a Cloud SQL MySQL 8.0 instance (Enterprise, Sandbox, 1 vCPU, single zone), connect MySQL Workbench to its public IP and run `sql/02_create_database_cloud.sql`. Then run `notebooks/02_cloud_pipeline.ipynb` once to load the static tables.
5. **Secrets:** in Secret Manager, create the secrets `password`, `openWeatherApi` and `AeroDATAboxAPI`.
6. **Cloud Functions:** create two Python 3.14 Cloud Run functions in europe-west1, both connected to the Cloud SQL instance:
   - `weather`: paste `cloud_functions/weather/main.py` and its `requirements.txt`, entry point `weather`
   - `flights`: paste `cloud_functions/flights/main.py` and its `requirements.txt`, entry point `flights`

   In each function, expose the secrets as environment variables with the same names, and add a plain environment variable `cloud_sql_host` holding the instance's public IP.
7. **Schedule:** in Cloud Scheduler, create one job per function with frequency `0 0 * * *` (every day at 00:00), Europe/Berlin time zone, target HTTP GET to the function URL.
8. **Clean up afterwards:** delete the Scheduler job, the function and the SQL instance, then shut down the project, so no free credits are wasted.

> ⚠️ For simplicity, the course set-up opens Cloud SQL to every IP address (`0.0.0.0/0`). That's fine for public weather and flight data, but in production you'd restrict the allowed networks and connect through the Cloud SQL connector or a private IP. (The secrets, at least, already live in Secret Manager.)

---

## 🚀 Future work

- **Close the loop with real demand:** join this data with Gans' own ride logs to measure how much rain or an evening wave of arrivals actually moves demand.
- **Forecast accuracy:** compare stored forecasts with what happened, to learn how far ahead the weather data can be trusted.
- **More cities:** extend the scraper beyond Germany, where Wikipedia infoboxes are less consistent.
- **Richer features:** public holidays, events and the hilliness of each district, three more known drivers of scooter asymmetry.
- **Production hardening:** retries and alerting on failed runs, and a private-IP database connection.

---

## 📧 Contact

- **LinkedIn:** [reetu-bhattacharjee](https://www.linkedin.com/in/reetu-bhattacharjee/)
- **GitHub:** [reetu-bhattacharjee](https://github.com/reetu-bhattacharjee)


*Built as part of the WBS Coding School Data Science bootcamp, Chapter: Data Pipelines on the Cloud.*
