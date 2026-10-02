# ============================================================
# FLIGHT CLOUD RUN FUNCTION (entry point: flights)
# ============================================================
#
# This is my LOCAL flight pipeline adapted for Cloud Run.
#
# Main changes from the local code are marked:
#     CLOUD RUN CHANGE
#
# The actual flight/API/SQL logic is kept as close as possible
# to my local working version.
# ============================================================


# ============================================================
# 1. IMPORTS
# ============================================================

import pysqlite3
import sys
import os
sys.modules["sqlite3"] = pysqlite3

import functions_framework
import requests
import pandas as pd


from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, URL, text




# ============================================================
# 2. DATABASE CONNECTION
# ============================================================

def create_database_engine():

    schema = "sql_cities_weather_flights"
    host = os.environ["cloud_sql_host"]   # public IP of the Cloud SQL instance
    user = "root"

    password = os.environ["password"]

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

    return engine


# ============================================================
# 3. FUNCTION FOR TOMORROW'S FLIGHT ARRIVALS
# ============================================================

def tomorrows_flight_arrivals(icao_list, headers):

    """
    Takes a list of ICAO airport codes.

    Returns a DataFrame containing tomorrow's arrivals.
    """



    berlin_timezone = ZoneInfo("Europe/Berlin")

    today = datetime.now(
        berlin_timezone
    ).date()

    tomorrow = today + timedelta(days=1)

    print("\nToday:", today)
    print("Tomorrow:", tomorrow)


    # --------------------------------------------------------
    # Store all flight records
    # --------------------------------------------------------

    list_for_arrivals_df = []


    # --------------------------------------------------------
    # Two time ranges
    # AeroDataBox FIDS endpoint accepts a maximum 12-hour range.
    # --------------------------------------------------------

    times = [
        ["00:00", "11:59"],
        ["12:00", "23:59"]
    ]


    # ========================================================
    # LOOP THROUGH EVERY ICAO AIRPORT
    # ========================================================

    for icao in icao_list:

        for time in times:

            from_local = (
                f"{tomorrow}T{time[0]}"
            )

            to_local = (
                f"{tomorrow}T{time[1]}"
            )


            # ------------------------------------------------
            # AeroDataBox FIDS endpoint
            # ------------------------------------------------

            url = (
                "https://aerodatabox.p.rapidapi.com/"
                f"flights/airports/icao/"
                f"{icao}/{from_local}/{to_local}"
            )


            querystring = {

                # Only arrivals
                "direction": "Arrival",

                # Include the other airport in the flight leg
                "withLeg": "true",

                # Exclude cancelled flights
                "withCancelled": "false",

                # Exclude codeshare duplicates
                "withCodeshared": "false",

                # Exclude cargo/private flights
                "withCargo": "false",
                "withPrivate": "false",

                # No aircraft location needed
                "withLocation": "false"
            }


            # =================================================
            # API REQUEST
            # =================================================

            response = requests.get(
                url,
                headers=headers,
                params=querystring,
                timeout=30
            )


            # ------------------------------------------------
            # RESPONSE
            # ------------------------------------------------

            if response.status_code != 200:

                print(
                    f"Flight request failed for {icao}: "
                    f"{response.status_code}"
                )

                print(response.text)

                continue


            # Convert JSON to Python dictionary
            flights_resp = response.json()


            # ------------------------------------------------
            # GET ARRIVALS
            # ------------------------------------------------

            arrivals = (
                flights_resp.get("arrivals")
                or []
            )


            print(
                f"{icao} | "
                f"{from_local} → {to_local} | "
                f"{len(arrivals)} arrivals"
            )


            # =================================================
            # EXTRACT EACH FLIGHT
            # =================================================

            for flight in arrivals:

                # ------------------------------------------------
                # FLIGHT NUMBER
                # ------------------------------------------------

                flight_number = (
                    flight.get("number")
                )


                # ------------------------------------------------
                # AIRLINE
                # ------------------------------------------------

                airline_data = (
                    flight.get("airline")
                    or {}
                )

                airline = (
                    airline_data.get("name")
                )


                # =================================================
                # ARRIVAL INFORMATION
                # =================================================

                arrival = (
                    flight.get("arrival")
                    or {}
                )


                # The airport we searched is the arrival airport
                arrival_airport_icao = icao


                # Terminal
                arrival_terminal = (
                    arrival.get("terminal")
                )


                # ------------------------------------------------
                # IMPORTANT: Use scheduledTime.
                # ------------------------------------------------

                scheduled_time = (
                    arrival.get("scheduledTime")
                    or {}
                )

                arrival_time = (
                    scheduled_time.get("local")
                )


                # =================================================
                # DEPARTURE INFORMATION
                # =================================================

                departure = (
                    flight.get("departure")
                    or {}
                )


                departure_airport = (
                    departure.get("airport")
                    or {}
                )


                departure_airport_icao = (
                    departure_airport.get("icao")
                )


                departure_airport_name = (
                    departure_airport.get("name")
                )


                departure_city = (
                    departure_airport.get(
                        "municipalityName"
                    )
                    or departure_airport_name
                )


                # =================================================
                # SKIP INCOMPLETE RECORDS
                # =================================================

                if not flight_number:
                    continue

                if not arrival_time:
                    continue

                if not departure_airport_icao:
                    continue


                # =================================================
                # CONVERT ARRIVAL DATETIME
                # =================================================

                arrival_time = pd.to_datetime(
                    arrival_time,
                    errors="coerce"
                )


                if pd.isna(arrival_time):
                    continue


                # ------------------------------------------------
                # Remove timezone because the MySQL column
                # is DATETIME.
                # ------------------------------------------------

                if arrival_time.tzinfo is not None:

                    arrival_time = (
                        arrival_time
                        .tz_localize(None)
                    )


                # =================================================
                # CREATE FLIGHT RECORD
                # =================================================

                arrivals_record = {

                    "arrival_airport_icao":
                        arrival_airport_icao,

                    "flight_number":
                        flight_number,

                    "airline":
                        airline,

                    "arrival_time":
                        arrival_time,

                    "arrival_terminal":
                        arrival_terminal,

                    "departure_city":
                        departure_city,

                    "departure_airport_icao":
                        departure_airport_icao,

                    "data_retrieved_on":
                        datetime.now(
                            berlin_timezone
                        ).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                }


                list_for_arrivals_df.append(
                    arrivals_record
                )


    # ========================================================
    # CREATE FINAL DATAFRAME
    # ========================================================

 

    if not list_for_arrivals_df:

        return pd.DataFrame(
            columns=[
                "arrival_airport_icao",
                "flight_number",
                "airline",
                "arrival_time",
                "arrival_terminal",
                "departure_city",
                "departure_airport_icao",
                "data_retrieved_on"
            ]
        )


    arrivals_df = pd.DataFrame(
        list_for_arrivals_df
    )


    # ========================================================
    # FINAL DATE CHECK
    # ========================================================

    # Even though we ask the API for tomorrow, we verify the
    # actual returned date.
    # --------------------------------------------------------

    arrivals_df = arrivals_df[
        arrivals_df["arrival_time"].dt.date
        == tomorrow
    ]


    # ========================================================
    # REMOVE DUPLICATES
    # ========================================================

    arrivals_df = arrivals_df.drop_duplicates(
        subset=[
            "arrival_airport_icao",
            "flight_number",
            "departure_airport_icao",
            "arrival_time"
        ]
    )


    # ========================================================
    # SORT BY ARRIVAL TIME
    # ========================================================

    arrivals_df = arrivals_df.sort_values(
        "arrival_time"
    ).reset_index(
        drop=True
    )


    return arrivals_df


# ============================================================
# 4. CLOUD RUN HTTP FUNCTION
# ============================================================

# ------------------------------------------------------------
# CLOUD RUN CHANGE
# ------------------------------------------------------------
# My local notebook/script runs from top to bottom.
#
# Cloud Run Functions need a function that Google can call.
#
# Therefore we create:
#
#     flights(request)
#
# and this becomes the function entry point.
# ------------------------------------------------------------

@functions_framework.http
def flights(request):

    try:

        print("\n==============================")
        print("Flight pipeline started")
        print("==============================")


        # ====================================================
        # 5. READ SECRETS
        # ====================================================

        # ----------------------------------------------------
        # CLOUD RUN CHANGE
        # ----------------------------------------------------
        # LOCAL:
        #     load_dotenv()
        #     API_key = os.getenv("AeroDATAboxAPI")
        #
        # CLOUD RUN:
        #     Secret Manager provides the value as an
        #     environment variable.
        # ----------------------------------------------------

        API_key = os.environ[
            "AeroDATAboxAPI"
        ]

        password = os.environ[
            "password"
        ]


        print(
            "AeroDataBox API key loaded:",
            bool(API_key)
        )

        print(
            "MySQL password loaded:",
            bool(password)
        )


        # ====================================================
        # 6. CREATE DATABASE ENGINE
        # ====================================================


        engine = create_database_engine()


        # ====================================================
        # 7. GET BERLIN, HAMBURG AND MUNICH FROM SQL
        # ====================================================

        cities_df = pd.read_sql(
            text("""
                SELECT
                    city_id,
                    city,
                    latitude,
                    longitude
                FROM cities
                WHERE city IN (
                    'Berlin',
                    'Hamburg',
                    'Munich'
                )
            """),
            con=engine
        )


        if cities_df.empty:

            raise ValueError(
                "Berlin, Hamburg and Munich were not "
                "found in the cities table."
            )


        print("\nCities used:")
        print(cities_df)


        # ====================================================
        # 8. AERODATABOX HEADERS
        # ====================================================


        headers = {

            "X-RapidAPI-Key":
                API_key,

            "X-RapidAPI-Host":
                "aerodatabox.p.rapidapi.com",

            "Content-Type":
                "application/json"
        }


        # ====================================================
        # 9. FIND AIRPORTS NEAR EACH CITY
        # ====================================================

       

        airport_records = []
        city_airport_records = []


        for _, city in cities_df.iterrows():

            city_id = city["city_id"]

            city_name = city["city"]

            latitude = city["latitude"]

            longitude = city["longitude"]


            url = (
                "https://aerodatabox.p.rapidapi.com/"
                "airports/search/location"
            )


            querystring = {

                "lat":
                    latitude,

                "lon":
                    longitude,

                "radiusKm":
                    50,

                "limit":
                    10,

                "withFlightInfoOnly":
                    "true"
            }


            response = requests.get(
                url,
                headers=headers,
                params=querystring,
                timeout=30
            )


            if response.status_code != 200:

                print(
                    f"Airport request failed for "
                    f"{city_name}: "
                    f"{response.status_code}"
                )

                print(response.text)

                continue


            data = response.json()


            for airport in data.get(
                "items",
                []
            ):

                airport_icao = (
                    airport.get("icao")
                )

                airport_name = (
                    airport.get("name")
                )


                if not airport_icao:
                    continue


                # ------------------------------------------------
                # AIRPORT TABLE RECORD
                # ------------------------------------------------

                airport_records.append({

                    "airport_icao":
                        airport_icao,

                    "airport_name":
                        airport_name
                })


                # ------------------------------------------------
                # CITY-AIRPORT RELATIONSHIP
                # ------------------------------------------------

                city_airport_records.append({

                    "city_id":
                        city_id,

                    "city":
                        city_name,

                    "airport_icao":
                        airport_icao
                })


        # ====================================================
        # 10. CREATE DATAFRAMES
        # ====================================================

        airports_df = pd.DataFrame(
            airport_records
        )

        city_airports_df = pd.DataFrame(
            city_airport_records
        )


        if not airports_df.empty:

            airports_df = (
                airports_df
                .drop_duplicates(
                    subset=["airport_icao"]
                )
            )


        if not city_airports_df.empty:

            city_airports_df = (
                city_airports_df
                .drop_duplicates(
                    subset=[
                        "city_id",
                        "airport_icao"
                    ]
                )
            )


        print("\nAirports found:")
        print(airports_df)


        print("\nCity-airport relationships:")
        print(city_airports_df)


        # ====================================================
        # 11. GET ICAO CODES
        # ====================================================

       

        icao_codes = (
            city_airports_df[
                "airport_icao"
            ]
            .drop_duplicates()
            .tolist()
        )


        print("\nICAO codes used:")
        print(icao_codes)


        # ====================================================
        # 12. GET TOMORROW'S ARRIVALS
        # ====================================================

       

        arrivals_df = (
            tomorrows_flight_arrivals(
                icao_codes,
                headers
            )
        )


        print("\nTomorrow's arrivals:")
        print(arrivals_df.head())


        print(
            "\nNumber of arriving flights:",
            len(arrivals_df)
        )


        # ====================================================
        # 13. CHECK DATES
        # ====================================================

        if not arrivals_df.empty:

            print(
                "\nDates contained in arrivals_df:"
            )

            print(
                arrivals_df[
                    "arrival_time"
                ]
                .dt
                .date
                .unique()
            )


        # ====================================================
        # 14. ADD DEPARTURE AIRPORTS
        # ====================================================


        route_airport_records = []


        if not arrivals_df.empty:

            for _, row in (
                arrivals_df.iterrows()
            ):

                route_airport_records.append({

                    "airport_icao":
                        row[
                            "departure_airport_icao"
                        ],

                    "airport_name":
                        row[
                            "departure_city"
                        ]
                })


        route_airports_df = (
            pd.DataFrame(
                route_airport_records
            )
        )


        if not route_airports_df.empty:

            route_airports_df = (
                route_airports_df
                .drop_duplicates(
                    subset=["airport_icao"]
                )
            )


        # ====================================================
        # 15. COMBINE AIRPORT DATA
        # ====================================================


        if not route_airports_df.empty:

            airports_df = pd.concat(

                [
                    airports_df,
                    route_airports_df
                ],

                ignore_index=True
            )


            airports_df = (
                airports_df
                .drop_duplicates(
                    subset=[
                        "airport_icao"
                    ],
                    keep="first"
                )
            )


        # ====================================================
        # 16. SAVE AIRPORTS TO SQL
        # ====================================================


        with engine.begin() as connection:

            for _, row in (
                airports_df.iterrows()
            ):

                # Do not insert missing names
                if pd.isna(
                    row["airport_name"]
                ):
                    continue


                connection.execute(

                    text("""
                        INSERT INTO airports (
                            airport_icao,
                            airport_name
                        )
                        VALUES (
                            :airport_icao,
                            :airport_name
                        )
                        ON DUPLICATE KEY UPDATE
                            airport_name =
                                VALUES(airport_name)
                    """),

                    {
                        "airport_icao":
                            row[
                                "airport_icao"
                            ],

                        "airport_name":
                            row[
                                "airport_name"
                            ]
                    }
                )


        # ====================================================
        # 17. SAVE CITY-AIRPORT RELATIONSHIPS
        # ====================================================


        if not city_airports_df.empty:

            with engine.begin() as connection:

                for _, row in (
                    city_airports_df.iterrows()
                ):

                    connection.execute(

                        text("""
                            INSERT IGNORE INTO
                            city_airports (
                                city_id,
                                city,
                                airport_icao
                            )
                            VALUES (
                                :city_id,
                                :city,
                                :airport_icao
                            )
                        """),

                        {
                            "city_id":
                                int(
                                    row[
                                        "city_id"
                                    ]
                                ),

                            "city":
                                row[
                                    "city"
                                ],

                            "airport_icao":
                                row[
                                    "airport_icao"
                                ]
                        }
                    )


        # ====================================================
        # 18. SAVE TOMORROW'S FLIGHTS
        # ====================================================


        if not arrivals_df.empty:

            with engine.begin() as connection:

                for _, row in (
                    arrivals_df.iterrows()
                ):

                    connection.execute(

                        text("""
                            INSERT IGNORE INTO flights (
                                flight_num,
                                departure_icao,
                                arrival_icao,
                                arrival_time
                            )
                            VALUES (
                                :flight_num,
                                :departure_icao,
                                :arrival_icao,
                                :arrival_time
                            )
                        """),

                        {
                            "flight_num":
                                row[
                                    "flight_number"
                                ],

                            "departure_icao":
                                row[
                                    "departure_airport_icao"
                                ],

                            "arrival_icao":
                                row[
                                    "arrival_airport_icao"
                                ],

                            "arrival_time":
                                row[
                                    "arrival_time"
                                ]
                        }
                    )


        # ====================================================
        # 19. SUCCESS RESPONSE
        # ====================================================

        # ----------------------------------------------------
        # CLOUD RUN CHANGE
        # ----------------------------------------------------
        # Local script ends with:
        #
        #     print("Flight pipeline completed.")
        #
        # A Cloud Run HTTP function should also return a
        # response to the caller.
        # ----------------------------------------------------

        message = (
            "Flight data successfully added: "
            f"{len(arrivals_df)} rows"
        )


        print("\n" + message)


        return message, 200


    # ========================================================
    # 20. ERROR HANDLING
    # ========================================================

    # --------------------------------------------------------
    # CLOUD RUN CHANGE
    # --------------------------------------------------------
    # Local notebooks show the Python error directly.
    #
    # In Cloud Run, returning the error as HTTP 500 makes the
    # function execution clearly show as failed.
    # --------------------------------------------------------

    except Exception as e:

        print("\nERROR:")
        print(str(e))


        return (
            f"Flight pipeline failed: {str(e)}",
            500
        )