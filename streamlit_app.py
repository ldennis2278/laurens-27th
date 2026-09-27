import hashlib
from html import escape
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components


DEFAULT_STOPS = ("Bar Flores", "Little Joy", "The Short Stop")
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")
STOP_COORDINATES = {
    "Bar Flores": (34.0763017, -118.2565015),
    "Little Joy": (34.0757226, -118.2544166),
    "The Short Stop": (34.0753503, -118.2535219),
}
DB_PATH = Path(os.getenv("CRAWL_DB_PATH", Path(__file__).with_name("crawl.sqlite3")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

location_tracker = components.declare_component(
    "location_tracker", path=str(Path(__file__).parent / "components" / "location_tracker")
)


def connect_db():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db():
    with connect_db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS crawls (
                crawl_id TEXT PRIMARY KEY,
                host_token_hash TEXT NOT NULL,
                stop_1 TEXT NOT NULL,
                stop_2 TEXT NOT NULL,
                stop_3 TEXT NOT NULL,
                venue TEXT,
                latitude REAL,
                longitude REAL,
                updated_at TEXT,
                status TEXT NOT NULL DEFAULT 'Waiting for a check-in'
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS crawl_markers (
                marker_id INTEGER PRIMARY KEY AUTOINCREMENT,
                crawl_id TEXT NOT NULL,
                label TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                is_current INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE (crawl_id, label)
            )"""
        )
        connection.execute(
            """INSERT OR IGNORE INTO crawl_markers
               (crawl_id, label, latitude, longitude, is_current, updated_at)
               SELECT crawl_id, venue, latitude, longitude, 1, COALESCE(updated_at, CURRENT_TIMESTAMP)
               FROM crawls
               WHERE status = 'Checked in' AND latitude IS NOT NULL AND longitude IS NOT NULL"""
        )


def create_crawl(stops):
    crawl_id = secrets.token_urlsafe(9)
    host_token = secrets.token_urlsafe(32)
    with connect_db() as connection:
        connection.execute(
            "INSERT INTO crawls (crawl_id, host_token_hash, stop_1, stop_2, stop_3) VALUES (?, ?, ?, ?, ?)",
            (crawl_id, hash_token(host_token), *stops),
        )
    return crawl_id, host_token


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def get_crawl(crawl_id):
    with connect_db() as connection:
        return connection.execute("SELECT * FROM crawls WHERE crawl_id = ?", (crawl_id,)).fetchone()


def update_stops(crawl_id, stops):
    with connect_db() as connection:
        connection.execute(
            "UPDATE crawls SET stop_1 = ?, stop_2 = ?, stop_3 = ? WHERE crawl_id = ?",
            (*stops, crawl_id),
        )


def update_location(crawl_id, venue, status, latitude=None, longitude=None):
    updated_at = datetime.now(timezone.utc).isoformat()
    with connect_db() as connection:
        connection.execute(
            """UPDATE crawls
               SET venue = ?, status = ?, latitude = ?, longitude = ?, updated_at = ?
               WHERE crawl_id = ?""",
            (venue, status, latitude, longitude, updated_at, crawl_id),
        )
        if status in ("Checked in", "Live GPS update") and latitude is not None and longitude is not None:
            label = "Live location" if status == "Live GPS update" else venue
            connection.execute(
                "UPDATE crawl_markers SET is_current = 0 WHERE crawl_id = ? AND is_current = 1",
                (crawl_id,),
            )
            connection.execute(
                """INSERT INTO crawl_markers
                   (crawl_id, label, latitude, longitude, is_current, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?)
                   ON CONFLICT(crawl_id, label) DO UPDATE SET
                   latitude = excluded.latitude,
                   longitude = excluded.longitude,
                   is_current = 1,
                   updated_at = excluded.updated_at""",
                (crawl_id, label, latitude, longitude, updated_at),
            )
        elif status == "GPS sharing paused":
            connection.execute(
                "UPDATE crawl_markers SET is_current = 0 WHERE crawl_id = ? AND label = 'Live location'",
                (crawl_id,),
            )


def map_points(crawl_id):
    with connect_db() as connection:
        return [
            dict(row)
            for row in connection.execute(
                """SELECT label, latitude, longitude, is_current
                   FROM crawl_markers
                   WHERE crawl_id = ? AND latitude IS NOT NULL AND longitude IS NOT NULL
                   ORDER BY updated_at""",
                (crawl_id,),
            )
        ]


def render_location_map(points, height):
    inactive_points = [point for point in points if not point["is_current"]]
    active_points = [point for point in points if point["is_current"]]
    center = active_points[-1] if active_points else points[-1]
    layers = []
    for data, color in ((inactive_points, [143, 145, 154, 220]), (active_points, [65, 166, 105, 245])):
        if data:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=data,
                    get_position="[longitude, latitude]",
                    get_radius=55,
                    radius_min_pixels=8,
                    radius_max_pixels=14,
                    get_fill_color=color,
                    get_line_color=[255, 255, 255, 230],
                    line_width_min_pixels=2,
                    stroked=True,
                    pickable=True,
                )
            )
    deck = pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=center["latitude"], longitude=center["longitude"], zoom=15),
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        tooltip={"text": "{label}"},
    )
    st.pydeck_chart(deck, height=height)


def make_share_url(crawl_id):
    current = urlsplit(st.context.url or "http://localhost/")
    return urlunsplit((current.scheme, current.netloc, current.path, urlencode({"crawl": crawl_id}), ""))


st.set_page_config(page_title="Lauren's Birthday in Echo Park!", page_icon="●", layout="wide")
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;500;600;700;800&display=swap');
    :root { --ink: #403348; --muted: #746a7d; --paper: #fff3f7; --pink: #f1c5d9; --blue: #dcecff; --purple: #e8e0f8; --border: #dcd2e6; }
    .stApp { background: var(--paper); color: var(--ink); font-family: 'Nunito', sans-serif; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] { background: var(--blue); }
    h1, h2, h3, p, label { font-family: 'Nunito', sans-serif; color: var(--ink); }
    h1 { letter-spacing: 0; font-size: 2.4rem; font-weight: 800; }
    .eyebrow { font: 700 0.72rem 'Nunito', sans-serif; letter-spacing: 0; text-transform: uppercase; color: var(--muted); }
    .status-band { background: var(--purple); color: var(--ink); border-radius: 8px; padding: 1.1rem 1.35rem; }
    .status-band strong { color: #6a5487; font-size: 1.2rem; }
    .status-band span { color: var(--muted); font: 500 0.76rem 'Nunito', sans-serif; }
    .stop-row { border-top: 1px solid var(--border); padding: 0.8rem 0; font-weight: 700; }
    div.stButton > button[kind="primary"] { background: var(--pink); border: 1px solid #dfabc5; color: var(--ink); font-weight: 800; }
    div.stButton > button { border-radius: 6px; }
    [data-testid="stMetric"] { background: var(--blue); border: 1px solid #cadcf0; border-radius: 8px; padding: 1rem; }
    [data-testid="stMetricLabel"] p { font: 700 0.7rem 'Nunito', sans-serif; text-transform: uppercase; }
    </style>
    """,
    unsafe_allow_html=True,
)

initialize_db()
params = st.query_params
crawl_id = params.get("crawl")
host_token = params.get("host")
crawl = get_crawl(crawl_id) if crawl_id else None
is_host = bool(crawl and host_token and secrets.compare_digest(hash_token(host_token), crawl["host_token_hash"]))

st.markdown('<div class="eyebrow">ECHO PARK · BAR CRAWL LIVE</div>', unsafe_allow_html=True)
st.title("Lauren's Birthday in Echo Park!")

if not crawl:
    st.write("Three stops. One live link. Your crew knows where to find you.")
    with st.form("new_crawl"):
        st.subheader("Set your three stops")
        stop_columns = st.columns(3)
        stops = [
            column.text_input(f"Stop {index + 1}", value=default, key=f"new_stop_{index}")
            for index, (column, default) in enumerate(zip(stop_columns, DEFAULT_STOPS))
        ]
        start = st.form_submit_button("Start a crawl", type="primary")
    if start:
        if any(not stop.strip() for stop in stops):
            st.error("Give all three stops a name to get started.")
        else:
            new_id, new_token = create_crawl([stop.strip() for stop in stops])
            st.query_params["crawl"] = new_id
            st.query_params["host"] = new_token
            st.rerun()
    st.stop()

if not is_host:
    @st.fragment(run_every=15)
    def render_crew_view(shared_crawl_id):
        current_crawl = get_crawl(shared_crawl_id)
        if not current_crawl:
            st.error("This crawl link is no longer available.")
            return
        st.markdown('<div class="eyebrow">PARTY VIEW</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="status-band"><span>RIGHT NOW</span><br><strong>{escape(current_crawl["venue"] or "No check-in yet")}</strong><br><span>{current_crawl["status"]}</span></div>',
            unsafe_allow_html=True,
        )
        if current_crawl["updated_at"]:
            updated = datetime.fromisoformat(current_crawl["updated_at"]).astimezone(LOCAL_TIMEZONE).strftime("%I:%M %p PT")
            st.caption(f"Last updated {updated}")
        points = map_points(shared_crawl_id)
        if points:
            render_location_map(points, height=420)
        st.subheader("Tonight's route")
        for index in range(1, 4):
            st.markdown(
                f'<div class="stop-row">0{index} &nbsp; {escape(current_crawl[f"stop_{index}"])}</div>',
                unsafe_allow_html=True,
            )

    render_crew_view(crawl_id)
    st.stop()

st.markdown('<div class="eyebrow">HOST VIEW</div>', unsafe_allow_html=True)
st.caption("Only people with your crew link can see this crawl. GPS sharing stays off until you turn it on.")
st.text_input("Crew link for friends", value=make_share_url(crawl_id), help="Copy this view-only link and send it to your friends.")

with st.sidebar:
    st.subheader("Tonight's stops")
    edited_stops = [
        st.text_input(f"Stop {index}", value=crawl[f"stop_{index}"], key=f"edit_stop_{index}")
        for index in range(1, 4)
    ]
    if st.button("Save stops"):
        if all(stop.strip() for stop in edited_stops):
            update_stops(crawl_id, [stop.strip() for stop in edited_stops])
            st.rerun()
        else:
            st.error("Each stop needs a name.")

if "tracking_enabled" not in st.session_state:
    st.session_state.tracking_enabled = False
tracking = st.toggle("Share live GPS", key="tracking_enabled")
if not tracking and st.session_state.get("tracking_was_enabled"):
    update_location(crawl_id, "Location hidden", "GPS sharing paused")
    crawl = get_crawl(crawl_id)
st.session_state.tracking_was_enabled = tracking
location = location_tracker(enabled=tracking, interval_seconds=15, default=None, key=f"tracker_{crawl_id}")
if tracking and isinstance(location, dict) and location.get("latitude") is not None:
    update_location(crawl_id, "Live location", "Live GPS update", location["latitude"], location["longitude"])
    crawl = get_crawl(crawl_id)

current_stops = [crawl[f"stop_{index}"] for index in range(1, 4)]
left, right = st.columns([1, 1.5], gap="large")
with left:
    st.subheader("Check in")
    selected_stop = st.selectbox("Choose where you are", current_stops)
    if st.button("Check in here", type="primary", use_container_width=True):
        coordinates = STOP_COORDINATES.get(selected_stop)
        latitude = crawl["latitude"] if tracking else coordinates[0] if coordinates else None
        longitude = crawl["longitude"] if tracking else coordinates[1] if coordinates else None
        update_location(crawl_id, selected_stop, "Checked in", latitude, longitude)
        st.rerun()
    if tracking:
        st.caption("Your browser will ask for location access. Updates are sent about every 15 seconds.")
with right:
    st.subheader("Live location")
    points = map_points(crawl_id)
    if points:
        render_location_map(points, height=340)
    else:
        st.info("Check in at a stop, or turn on live GPS to share your position here.")
