from api_testing.request_calls import ServerApi
import time
import json

# File paths
LOG_FILE = "system_monitor.log"
EXCEPTION_FILE = "exception.log"

# Thresholds for exceptional values
TEMP_THRESHOLD = 70
CPU_THRESHOLD = 90.0  # CPU usage threshold in percentage

MONITOR_INTERVAL = 5  # seconds


def load_config(config_path: str) -> dict:
    """Load configuration from a JSON file."""
    with open(config_path, "r") as config_file:
        return json.load(config_file)


def get_temp(p_name: str, server: ServerApi) -> int:
    resp = server.send_player_command(
        player_name=p_name,
        command="cat /sys/devices/virtual/thermal/thermal_zone?/temp | head -n 1"
    ).get("data", {}).get("stdout", "")
    return int(resp) // 1000


def get_cpu(p_name: str, server: ServerApi) -> float:
    return float(server.send_player_command(
        player_name=p_name,
        command="top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'"
    ).get("data", {}).get("stdout", ""))  # add up the user and system usage


if __name__ == "__main__":
    CONFIG_FILE = "login_watcher.json"
    config = load_config(CONFIG_FILE)

    server = ServerApi(url=config["url"], login=config["login"], password=config["password"])
    player_name = "RPIX01_PB0005__"

    with open(LOG_FILE, "w") as log_file:
        log_file.write("Timestamp,Temperature (°C),CPU Usage (%)\n")

    with open(EXCEPTION_FILE, "w") as exception_file:
        exception_file.write("Timestamp,Temperature (°C),CPU Usage (%)\n")

    while True:
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            temp = get_temp(player_name, server)
            cpu = get_cpu(player_name, server)

            log_entry = f"{timestamp},{temp},{cpu}\n"

            # Write to main log
            with open(LOG_FILE, "a") as log_file:
                log_file.write(log_entry)

            # Check for exceptional values and log them
            if temp > TEMP_THRESHOLD or cpu > CPU_THRESHOLD:
                with open(EXCEPTION_FILE, "a") as exception_file:
                    exception_file.write(log_entry)

        except Exception as e:
            print(f"Error occurred: {e}")

        time.sleep(MONITOR_INTERVAL)
