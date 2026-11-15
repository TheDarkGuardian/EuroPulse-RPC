import ctypes
import json
import logging
import math
import os
import re
import sys
import time
from logging.handlers import RotatingFileHandler

import psutil
import truck_telemetry
from pypresence import Presence

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CITIES_PATH = os.path.join(APP_DIR, "cities_ets2.json")
LOG_PATH = os.path.join(APP_DIR, "rpc.log")
GAME_LOG_PATH = os.path.join(
    os.path.expanduser("~"), "Documents", "Euro Truck Simulator 2", "game.log.txt"
)

# Discord's official detectable Euro Truck Simulator 2 application ID
DISCORD_APP_ID = "1402418075726254102"

COACHES_COVER_URL = (
    "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/"
    "3809270/76265f5ca82a7e38ef486f169108f08379785a51/header.jpg"
)
ETS2_ICON_URL = (
    "https://cdn.discordapp.com/app-icons/1402418075726254102/"
    "46bfdfc58e4eacbfde29b2461e118e78.png?size=256"
)
ETS2_LOGO_ASSET_URL = (
    "https://cdn.discordapp.com/app-assets/529016610137309184/529055946031366144.png"
)

BRAND_ICONS = {
    "scania": "https://cdn.discordapp.com/app-assets/529016610137309184/529054145357938719.png",
    "man": "https://cdn.discordapp.com/app-assets/529016610137309184/529340038589448200.png",
    "volvo": "https://cdn.discordapp.com/app-assets/529016610137309184/529340646339903490.png",
    "mercedes": "https://cdn.discordapp.com/app-assets/529016610137309184/646820650689888256.png",
    "mercedes-benz": "https://cdn.discordapp.com/app-assets/529016610137309184/646820650689888256.png",
    "daf": "https://cdn.discordapp.com/app-assets/529016610137309184/770390071890542652.png",
    "iveco": "https://cdn.discordapp.com/app-assets/529016610137309184/529286008663965707.png",
    "renault": "https://cdn.discordapp.com/app-assets/529016610137309184/529340427896094761.png",
    "skoda": "https://cdn.discordapp.com/app-assets/529016610137309184/770401916894576691.png",
    "scout": "https://cdn.discordapp.com/app-assets/529016610137309184/770401916894576691.png",
}

BUS_KEYWORDS = (
    "bus",
    "coach",
    "touring",
    "lion",
    "9700",
    "setra",
    "irizar",
    "travego",
    "tourismo",
    "neoplan",
    "marcopolo",
    "temsa",
    "otokar",
    "passenger",
)

CAR_KEYWORDS = ("skoda", "superb", "scout", "mustang", "car")

POLL_INTERVAL_IDLE = 5
POLL_INTERVAL_ACTIVE = 5


def setup_logging():
    logger = logging.getLogger("ets2_rpc")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        LOG_PATH, maxBytes=512 * 1024, backupCount=1, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if sys.stdout and sys.stdout.isatty():
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger


def acquire_single_instance_mutex():
    """Ensure only one instance of the background RPC service runs at a time."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\ETS2_Discord_RPC_Mutex")
    last_error = kernel32.GetLastError()
    if last_error == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def load_cities():
    with open(CITIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def find_nearest_city(cities, x, z):
    if not cities:
        return None
    best = min(cities, key=lambda c: (c["x"] - x) ** 2 + (c["z"] - z) ** 2)
    return best


def find_ets2_process():
    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            name = proc.info.get("name") or ""
            if name.lower() == "eurotrucks2.exe":
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def truncate_rpc(text, limit=128):
    if not text:
        return None
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class GameLogReader:
    """Lightweight cached reader for ETS2 game.log.txt (suspension class & fallback coords)."""

    def __init__(self, path):
        self.path = path
        self._last_mtime = 0.0
        self._last_size = -1
        self.vehicle_class = None
        self.has_bus_dlc = False
        self.last_coords = None

    def refresh(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return
        if st.st_mtime == self._last_mtime and st.st_size == self._last_size:
            return
        self._last_mtime = st.st_mtime
        self._last_size = st.st_size
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return

        if "dlc_bus.scs" in content:
            self.has_bus_dlc = True

        classes = re.findall(r"\[actor\] Vehicle suspension class is (\w+)\.", content)
        if not classes:
            classes = re.findall(r"Desktop screen config switched to '(\w+)'", content)
        if classes:
            self.vehicle_class = classes[-1].lower()

        coords = re.findall(
            r"\[actor\] Initialized at \[([-\d.]+);([-\d.]+);([-\d.]+)\]", content
        )
        if coords:
            cx, _, cz = coords[-1]
            self.last_coords = (float(cx), float(cz))


def format_gear(gear_dash):
    if gear_dash > 0:
        return f"D{gear_dash}"
    if gear_dash < 0:
        return "R" if gear_dash == -1 else f"R{abs(gear_dash)}"
    return "N"


def resolve_brand_icon(brand_id, brand):
    key = (brand_id or brand or "").strip().lower()
    for candidate, url in BRAND_ICONS.items():
        if candidate in key:
            return url
    return ETS2_ICON_URL


def detect_vehicle_mode(data, log_reader):
    brand_id = (data.get("truckBrandId") or "").strip().lower()
    brand = (data.get("truckBrand") or "").strip()
    model = (data.get("truckName") or "").strip()
    truck_id = (data.get("truckId") or "").strip().lower()
    job_market = (data.get("jobMarket") or "").strip().lower()
    cargo_id = (data.get("cargoId") or "").strip().lower()
    cargo = (data.get("cargo") or "").strip().lower()

    haystack = " ".join([brand_id, brand.lower(), model.lower(), truck_id, job_market, cargo_id, cargo])

    is_bus = (
        log_reader.vehicle_class == "bus"
        or any(k in haystack for k in BUS_KEYWORDS)
    )
    is_car = not is_bus and (
        log_reader.vehicle_class == "car"
        or any(k in haystack for k in CAR_KEYWORDS)
    )

    if brand and model:
        if brand.lower() in model.lower():
            vehicle_label = model
        else:
            vehicle_label = f"{brand} {model}"
    else:
        vehicle_label = model or brand or ""

    return is_bus, is_car, vehicle_label


def build_telemetry_payload(data, cities, log_reader, ets2_pid, start_ts):
    paused = bool(data.get("paused", False))
    x = float(data.get("coordinateX", 0.0))
    z = float(data.get("coordinateZ", 0.0))
    speed_ms = abs(float(data.get("speed", 0.0)))
    speed_kmh = int(round(speed_ms * 3.6))
    rpm = int(round(float(data.get("engineRpm", 0.0))))
    gear_dash = int(data.get("gearDashboard", 0))
    gear_str = format_gear(gear_dash)

    brand_id = (data.get("truckBrandId") or "").strip()
    brand = (data.get("truckBrand") or "").strip()
    plate = (data.get("truckLicensePlate") or "").strip()
    plate_suffix = f" ({plate})" if plate else ""
    is_bus, is_car, vehicle_label = detect_vehicle_mode(data, log_reader)

    on_job = bool(data.get("onJob", False))
    cargo = (data.get("cargo") or "").strip()
    cargo_mass_t = int(round(float(data.get("cargoMass", 0.0)) / 1000.0))
    city_src = (data.get("citySrc") or "").strip()
    city_dst = (data.get("cityDst") or "").strip()
    route_dist_km = int(round(float(data.get("routeDistance", 0.0)) / 1000.0))

    in_world = abs(x) > 0.01 or abs(z) > 0.01
    nearest = find_nearest_city(cities, x, z) if in_world else None
    city_text = f"{nearest['name']} ({nearest['country']})" if nearest else "Avrupa Yolları"

    icon_emoji = "🚌" if is_bus else ("🚗" if is_car else "🚛")
    small_image = resolve_brand_icon(brand_id, brand)

    if is_bus:
        large_image = COACHES_COVER_URL
        large_text = (
            f"Coaches DLC • {vehicle_label}{plate_suffix}"
            if vehicle_label
            else "Euro Truck Simulator 2 • Coaches DLC"
        )
    else:
        large_image = ETS2_LOGO_ASSET_URL
        large_text = vehicle_label or "Euro Truck Simulator 2"

    if not in_world:
        details = "🎮 Ana Menüde"
        state = "🚌 Coaches DLC • Otobüs Hazırlığı" if is_bus else "🚛 Sefer planlıyor..."
        small_text = vehicle_label or "Euro Truck Simulator 2"
    elif paused:
        if is_bus:
            if city_src and city_dst:
                details = f"⏸️ Mola • 🚌 {city_src} ➔ {city_dst}"
            elif route_dist_km > 0:
                details = f"⏸️ Mola • 🚌 {vehicle_label or 'Coaches DLC'} ({route_dist_km} km)"
            else:
                details = f"⏸️ Mola • 🚌 {vehicle_label or 'Coaches DLC'}"
        elif on_job and city_src and city_dst:
            details = f"⏸️ Mola • {icon_emoji} {city_src} ➔ {city_dst}"
        else:
            details = "⏸️ Menüde / Mola"
        state = f"📍 {city_text}"
        small_text = f"{vehicle_label} • Park Halinde" if vehicle_label else "Menüde"
    else:
        if is_bus:
            if city_src and city_dst:
                dist_part = f" ({route_dist_km} km)" if route_dist_km > 0 else ""
                details = f"🚌 Hat: {city_src} ➔ {city_dst}{dist_part}"
            elif route_dist_km > 0:
                details = f"🚌 {vehicle_label or 'Coaches DLC'} • Rotada {route_dist_km} km"
            elif vehicle_label:
                details = f"🚌 Coaches DLC • {vehicle_label}"
            else:
                details = "🚌 Coaches DLC • Otobüs Sürüşü"
        else:
            if on_job and city_src and city_dst:
                cargo_part = f"{cargo} ({cargo_mass_t}t) • " if (cargo and cargo_mass_t > 0) else (f"{cargo} • " if cargo else "")
                dist_part = f" ({route_dist_km} km)" if route_dist_km > 0 else ""
                details = f"🚛 {cargo_part}{city_src} ➔ {city_dst}{dist_part}"
            elif vehicle_label:
                details = f"{icon_emoji} Serbest Sürüş • {vehicle_label}"
            else:
                details = f"{icon_emoji} Serbest Sürüş"

        state = f"📍 {city_text} • ⚡ {speed_kmh} km/s"
        if vehicle_label:
            small_text = f"{icon_emoji} {vehicle_label}{plate_suffix} • Vites: {gear_str} • {rpm} RPM"
        else:
            small_text = f"{icon_emoji} Vites: {gear_str} • {rpm} RPM"

    return {
        "pid": ets2_pid,
        "details": truncate_rpc(details),
        "state": truncate_rpc(state),
        "start": int(start_ts),
        "large_image": large_image,
        "large_text": truncate_rpc(large_text),
        "small_image": small_image,
        "small_text": truncate_rpc(small_text),
    }


def build_fallback_payload(cities, log_reader, ets2_pid, start_ts):
    """Used only if ETS2 was started before scs-telemetry.dll was loaded."""
    is_bus = log_reader.vehicle_class == "bus" or log_reader.has_bus_dlc
    if log_reader.last_coords:
        nearest = find_nearest_city(cities, *log_reader.last_coords)
        city_text = f"{nearest['name']} ({nearest['country']})" if nearest else "Avrupa Yolları"
    else:
        city_text = "Avrupa Yolları"

    if is_bus:
        details = "🚌 Coaches DLC • Otobüs Sürüşü"
        large_image = COACHES_COVER_URL
        large_text = "Euro Truck Simulator 2 • Coaches DLC"
        small_text = "Canlı hız için oyunu yeniden başlatın"
    else:
        details = "🚛 Euro Truck Simulator 2"
        large_image = ETS2_LOGO_ASSET_URL
        large_text = "Euro Truck Simulator 2"
        small_text = "Canlı hız için oyunu yeniden başlatın"

    return {
        "pid": ets2_pid,
        "details": truncate_rpc(details),
        "state": truncate_rpc(f"📍 {city_text}"),
        "start": int(start_ts),
        "large_image": large_image,
        "large_text": truncate_rpc(large_text),
        "small_image": ETS2_ICON_URL,
        "small_text": truncate_rpc(small_text),
    }


def main():
    logger = setup_logging()
    mutex = acquire_single_instance_mutex()
    if mutex is None:
        logger.info("Another instance of ETS2 Discord RPC is already running. Exiting.")
        return

    logger.info("ETS2 Discord RPC background service started.")
    cities = load_cities()
    logger.info(f"Loaded {len(cities)} cities from database.")
    log_reader = GameLogReader(GAME_LOG_PATH)

    rpc = None
    telemetry_ready = False
    last_payload = None
    logged_waiting_telemetry = False
    logged_first_rpc_response = False

    while True:
        try:
            ets2_proc = find_ets2_process()
            if ets2_proc is None:
                if telemetry_ready:
                    try:
                        truck_telemetry.deinit()
                    except Exception:
                        pass
                    telemetry_ready = False
                if rpc is not None:
                    logger.info("ETS2 closed. Disconnecting Discord RPC.")
                    try:
                        rpc.clear()
                    except Exception:
                        pass
                    try:
                        rpc.close()
                    except Exception:
                        pass
                    rpc = None
                    last_payload = None
                    logged_first_rpc_response = False
                logged_waiting_telemetry = False
                time.sleep(POLL_INTERVAL_IDLE)
                continue

            # ETS2 is running
            ets2_pid = ets2_proc.pid
            try:
                start_ts = ets2_proc.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                start_ts = time.time()

            # Connect to Discord if not connected
            if rpc is None:
                try:
                    candidate = Presence(DISCORD_APP_ID)
                    candidate.connect()
                    rpc = candidate
                    last_payload = None
                    logged_first_rpc_response = False
                    logger.info(f"Connected to Discord IPC for ETS2 (PID {ets2_pid}).")
                except Exception as e:
                    logger.debug(f"Discord not ready yet: {e}")
                    time.sleep(POLL_INTERVAL_IDLE)
                    continue

            log_reader.refresh()

            # Try initializing telemetry shared memory if not yet attached
            if not telemetry_ready:
                try:
                    truck_telemetry.init()
                    telemetry_ready = True
                    logged_waiting_telemetry = False
                    logger.info("Attached to Local\\SCSTelemetry shared memory (live telemetry active).")
                except FileNotFoundError:
                    if not logged_waiting_telemetry:
                        logger.info(
                            "Local\\SCSTelemetry not found yet (game needs restart to load scs-telemetry.dll). Using game.log fallback."
                        )
                        logged_waiting_telemetry = True
                except Exception as e:
                    logger.warning(f"Telemetry init error: {e}")

            payload = None
            if telemetry_ready:
                try:
                    data = truck_telemetry.get_data()
                    if data and data.get("sdkActive"):
                        payload = build_telemetry_payload(
                            data, cities, log_reader, ets2_pid, start_ts
                        )
                    else:
                        payload = build_fallback_payload(
                            cities, log_reader, ets2_pid, start_ts
                        )
                except Exception as e:
                    logger.warning(f"Telemetry read error, detaching: {e}")
                    try:
                        truck_telemetry.deinit()
                    except Exception:
                        pass
                    telemetry_ready = False
                    payload = build_fallback_payload(
                        cities, log_reader, ets2_pid, start_ts
                    )
            else:
                payload = build_fallback_payload(
                    cities, log_reader, ets2_pid, start_ts
                )

            if payload and payload != last_payload:
                try:
                    res = rpc.update(**payload)
                    last_payload = payload
                    if not logged_first_rpc_response:
                        logger.info(f"Discord SET_ACTIVITY response: {res}")
                        logged_first_rpc_response = True
                    logger.info(
                        f"Updated RPC -> {payload['details']} | {payload['state']}"
                    )
                except Exception as e:
                    logger.warning(f"Discord RPC update failed, reconnecting: {e}")
                    try:
                        rpc.close()
                    except Exception:
                        pass
                    rpc = None
                    last_payload = None
                    logged_first_rpc_response = False

            time.sleep(POLL_INTERVAL_ACTIVE)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.exception(f"Unexpected loop error: {e}")
            time.sleep(POLL_INTERVAL_IDLE)

    if telemetry_ready:
        try:
            truck_telemetry.deinit()
        except Exception:
            pass
    if rpc is not None:
        try:
            rpc.clear()
            rpc.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
