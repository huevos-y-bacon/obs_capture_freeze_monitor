#!/usr/bin/env python3
# pylint: disable=W0718,W0719,W1203,C0301,W1309,W0613
"""
OBS Capture Monitor

Monitors a Capture source in OBS Studio and automatically restarts
it when the source becomes inactive or non-functional.

Uses OBS WebSocket API for reliable monitoring without pixel monitoring.
Designed to run completely in background on macOS.

Credits:
- This script is inspired by the work of yayuanli on GitHub - https://github.com/yayuanli/OBS_Restart_Capture_Stuck_Source
- It is designed to be run as a background service on macOS.
"""

import sys
import asyncio
import json
import logging
import signal
import time
import base64
import hashlib
import threading
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

# OBS > Tools > WebSocket Server Settings > Show Connect Info > Server Password
PASSWORD = "uziPSvQHt8IC35sn" # Replace with your OBS WebSocket password
HOST = "localhost"
PORT = 4455
CHECK_INTERVAL = 60  # seconds

LOG_DIR = "/var/log/obs_capture_monitor"
LOG_PATH = f"{LOG_DIR}/obs_capture_monitor.log"

print(f"Logging to {LOG_PATH}")

try:
    sys.stdout = open(LOG_PATH, "a", buffering=1, encoding="utf-8")
    sys.stderr = open(LOG_PATH, "a", buffering=1, encoding="utf-8")
except Exception as e:
    print(f"Failed to redirect output to log file: {LOG_PATH}")
    print(f"Error: {e}\n")
    print("Run the following commands to prepare the log location:\n")
    print(f"sudo mkdir -p {LOG_DIR}")
    print(f"sudo touch {LOG_PATH}")
    print(f"sudo chown $USER:\"wheel\" {LOG_PATH}")
    sys.exit(1)

try:
    import websocket
except ImportError:
    print("Error: websocket-client not installed. Run: pip install websocket-client")
    sys.exit(1)

class OBSCaptureMonitor:
    """
    OBSCaptureMonitor monitors a specific Capture source in OBS Studio
    and automatically restarts it if it becomes inactive or frozen.
    This class uses the OBS WebSocket API to interact with OBS Studio.
    """
    def __init__(self, source_name, host, port, password, interval, threshold, cooldown):
        self.source_name = source_name
        self.host = host
        self.port = port
        self.password = password
        self.ws = None
        self.running = True
        self.monitor_interval = interval
        self.stuck_threshold = threshold
        self.last_restart = 0
        self.restart_cooldown = cooldown
        self.request_id = 1

        # Setup logging
        self.setup_logging()

    def setup_logging(self):
        """Setup logging configuration with source name in every log entry"""
        log_file = Path(LOG_PATH)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        class SourceFilter(logging.Filter):
            """Custom filter to add source name to log records"""
            def __init__(self, source_name):
                super().__init__()
                self.source_name = source_name
            def filter(self, record):
                record.source = self.source_name
                return True

        log_format = '%(asctime)s - %(levelname)s - [%(source)s] %(message)s'
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        self.logger.addFilter(SourceFilter(self.source_name))

    def _build_auth_string(self, salt, challenge):
        """Build authentication string for OBS WebSocket"""
        secret = base64.b64encode(
            hashlib.sha256(
                (self.password + salt).encode('utf-8')
            ).digest()
        )
        auth = base64.b64encode(
            hashlib.sha256(
                secret + challenge.encode('utf-8')
            ).digest()
        ).decode('utf-8')
        return auth

    def _authenticate(self):
        """Authenticate with OBS WebSocket"""
        try:
            # Receive hello message
            message = self.ws.recv() # type: ignore
            result = json.loads(message)

            if result.get('op') != 0:  # Hello OpCode
                raise Exception("Expected Hello message")

            auth_data = result['d'].get('authentication')
            if auth_data and self.password:
                # Build auth string
                auth = self._build_auth_string(
                    auth_data['salt'],
                    auth_data['challenge']
                )

                # Send Identify with auth and subscribe to all input events
                payload = {
                    "op": 1,  # Identify OpCode
                    "d": {
                        "rpcVersion": 1,
                        "authentication": auth,
                        "eventSubscriptions": 33 | (1 << 14)  # General events + Input events
                    }
                }
            else:
                # Send Identify without auth but with input events subscription
                payload = {
                    "op": 1,  # Identify OpCode
                    "d": {
                        "rpcVersion": 1,
                        "eventSubscriptions": 33 | (1 << 14)  # General events + Input events
                    }
                }

            self.ws.send(json.dumps(payload)) # type: ignore

            # Receive Identified message
            message = self.ws.recv() # type: ignore
            result = json.loads(message)

            if result.get('op') != 2:  # Identified OpCode
                raise Exception(f"Authentication failed: {result}")

            return True

        except Exception as e:
            self.logger.error(f"Authentication failed: {e}")
            return False

    def connect_to_obs(self):
        """Establish connection to OBS WebSocket"""
        try:
            self.logger.info(f"Connecting to OBS WebSocket at {self.host}:{self.port}")
            url = f"ws://{self.host}:{self.port}"
            self.ws = websocket.create_connection(url)

            # Authenticate
            if not self._authenticate():
                return False

            # Test connection by getting version
            version_response = self._send_request("GetVersion")
            if version_response:
                obs_version = version_response.get('responseData', {}).get('obsVersion', 'Unknown')
                self.logger.info(f"Connected to OBS Studio {obs_version}")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Failed to connect to OBS: {e}")
            return False

    def disconnect_from_obs(self):
        """Disconnect from OBS WebSocket"""
        if self.ws:
            try:
                self.ws.close()
                self.logger.info("Disconnected from OBS WebSocket")
            except Exception as e:
                self.logger.error(f"Error disconnecting from OBS: {e}")
            finally:
                self.ws = None

    def _send_request(self, request_type, request_data=None):
        """Send a request to OBS and return the response"""
        if not self.ws:
            return None

        try:
            request_id = f"req_{self.request_id}"
            self.request_id += 1

            payload = {
                "op": 6,  # Request OpCode
                "d": {
                    "requestId": request_id,
                    "requestType": request_type,
                    "requestData": request_data or {}
                }
            }

            self.ws.send(json.dumps(payload))

            # Wait for response
            message = self.ws.recv()
            response = json.loads(message)

            if response.get('op') == 7 and response.get('d', {}).get('requestId') == request_id:
                return response.get('d')

            return None

        except Exception as e:
            self.logger.error(f"Error sending request {request_type}: {e}")
            return None

    def check_source_exists(self):
        """Check if the target source exists in OBS"""
        try:
            self.logger.info(f"Checking if source '{self.source_name}' exists...")
            response = self._send_request("GetInputList")
            self.logger.debug(f"GetInputList response: {response}")

            if not response:
                self.logger.error("No response from GetInputList")
                return False

            inputs = response.get('responseData', {}).get('inputs', [])
            input_names = [inp.get('inputName', '') for inp in inputs]

            self.logger.info(f"Found {len(inputs)} inputs in OBS: {input_names}")

            if self.source_name not in input_names:
                self.logger.error(f"Source '{self.source_name}' not found in OBS")
                self.logger.info(f"Available inputs: {', '.join(input_names)}")
                return False

            self.logger.info(f"✓ Source '{self.source_name}' found in OBS")
            return True

        except Exception as e:
            self.logger.error(f"Error checking source existence: {e}")
            return False

    def _is_source_frozen(self, prev_hash):
        """
        Check if the source is frozen by comparing screenshot hashes.
        Returns a tuple: (is_frozen, current_hash)
        """
        current_hash = self._get_screenshot_hash()

        if current_hash is None:
            self.logger.warning("⚠️ Failed to get screenshot, cannot determine state.")
            return False, prev_hash # Assume not frozen if we can't get a screenshot

        is_frozen = (current_hash == prev_hash) # pylint: disable=C0325
        return is_frozen, current_hash

    def _get_screenshot_hash(self):
        """Get MD5 hash of current source screenshot."""
        try:
            response = self._send_request("GetSourceScreenshot", {
                "sourceName": self.source_name,
                "imageFormat": "png",
                "imageWidth": 320,  # Small size for quick comparison
                "imageHeight": 180,
                "imageCompressionQuality": 50
            })

            if response and 'responseData' in response:
                # Extract base64 data from data URL
                image_data = response['responseData']['imageData'].split(',', 1)[1]
                # Get MD5 hash of the image data
                return hashlib.md5(base64.b64decode(image_data)).hexdigest()
            return None
        except Exception as e:
            self.logger.error(f"Failed to get screenshot: {e}")
            return None

    def _restart_capture(self):
        """Restart the display capture source by toggling capture settings"""
        try:
            current_time = time.time()
            if current_time - self.last_restart < self.restart_cooldown:
                self.logger.info("⏳ Skipping restart - cooldown period active")
                return False

            self.logger.warning(f"{'='*50}")
            self.logger.warning("🔄 RESTARTING DISPLAY CAPTURE")
            self.logger.warning(f"Source: {self.source_name}")
            self.logger.warning(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            # Get current settings
            settings_response = self._send_request("GetInputSettings", {
                "inputName": self.source_name
            })

            if not settings_response or 'responseData' not in settings_response:
                self.logger.error("Failed to get source settings")
                return False

            current_settings = settings_response['responseData'].get('inputSettings', {})
            self.logger.debug(f"Current settings: {json.dumps(current_settings, indent=2)}")

            # Method 1: Toggle capture type between window and display
            original_type = current_settings.get('type', 0)
            new_type = 1 if original_type == 0 else 0

            # Change to opposite type
            self._send_request("SetInputSettings", {
                "inputName": self.source_name,
                "inputSettings": {**current_settings, "type": new_type}
            })
            time.sleep(0.5)

            # Change back to original type
            response = self._send_request("SetInputSettings", {
                "inputName": self.source_name,
                "inputSettings": {**current_settings, "type": original_type}
            })

            if response and response.get('requestStatus', {}).get('result'):
                self.last_restart = current_time
                self.logger.warning("✅ Restart completed")
                self.logger.warning(f"{'='*50}")
                return True

            self.logger.error("❌ Restart failed")
            return False

        except Exception as e:
            self.logger.error(f"❌ Failed to restart capture: {e}")
            return False

    async def monitor_loop(self):
        """Main monitoring loop using screenshot comparison."""
        self.logger.info(f"Starting monitor loop for source '{self.source_name}'")
        self.logger.info(f"Monitor interval: {self.monitor_interval}s, Stuck threshold: {self.stuck_threshold} frames")

        prev_hash = None
        identical_count = 0
        check_count = 0

        while self.running:
            try:
                check_count += 1
                self.logger.info(f"=== Check #{check_count} ===")

                is_frozen, current_hash = await asyncio.to_thread(self._is_source_frozen, prev_hash)

                if is_frozen:
                    identical_count += 1
                    self.logger.warning(f"⚠️ Identical frame detected (count: {identical_count}/{self.stuck_threshold})")

                    if identical_count >= self.stuck_threshold:
                        self.logger.warning("❗ capture appears to be frozen")
                        if self._restart_capture():
                            identical_count = 0  # Reset counter after restart
                            # After a restart, the hash will be different, so we fetch a new one
                            current_hash = self._get_screenshot_hash()
                else:
                    if identical_count > 0:
                        self.logger.info("✅ Frame changed - display capture is active")
                    identical_count = 0

                prev_hash = current_hash
                await asyncio.sleep(self.monitor_interval)

            except Exception as e:
                self.logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(2)  # Wait before retrying

    def signal_handler(self, signum, frame): # type: ignore
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def start(self):
        """Start the monitoring service"""
        # import threading
        # Setup signal handlers for graceful shutdown only in main thread
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)

        self.logger.info("Starting OBS Capture Monitor")

        # Connect to OBS
        if not self.connect_to_obs():
            self.logger.error("Failed to connect to OBS. Exiting.")
            return False

        # Verify source exists
        if not self.check_source_exists():
            self.logger.error("Target source not found. Exiting.")
            self.disconnect_from_obs()
            return False

        self.running = True

        try:
            # Run the monitoring loop
            asyncio.run(self.monitor_loop())
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        finally:
            self.stop()

        return True

    async def async_start(self):
        """Async version of start for parallel monitoring."""
        # Setup signal handlers for graceful shutdown only in main thread
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self.signal_handler)
            signal.signal(signal.SIGTERM, self.signal_handler)

        self.logger.info("Starting OBS Capture Monitor")

        # Connect to OBS
        if not self.connect_to_obs():
            self.logger.error("Failed to connect to OBS. Exiting.")
            return False

        # Verify source exists
        if not self.check_source_exists():
            self.logger.error("Target source not found. Exiting.")
            self.disconnect_from_obs()
            return False

        self.running = True

        try:
            await self.monitor_loop()
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
        finally:
            self.stop()

        return True

    def stop(self):
        """Stop the monitoring service"""
        self.logger.info("Stopping OBS Capture Monitor")
        self.running = False
        self.disconnect_from_obs()


class OBSMultiSourceMonitor:
    """Monitor multiple sources using a single OBS WebSocket connection."""
    def __init__(self, source_names, host, port, password, interval, threshold, cooldown):
        self.source_names = source_names
        self.host = host
        self.port = port
        self.password = password
        self.interval = interval
        self.threshold = threshold
        self.cooldown = cooldown
        self.ws = None
        self.last_restart: Dict[str, float] = {name: 0.0 for name in source_names}
        self.prev_hash: Dict[str, Optional[str]] = {name: None for name in source_names}
        self.identical_count = {name: 0 for name in source_names}
        self.running = True
        self.logger = logging.getLogger("multi")

    def connect(self):
        """Connect to OBS WebSocket and authenticate."""
        try:
            url = f"ws://{self.host}:{self.port}"
            self.ws = websocket.create_connection(url)
            # Authenticate
            message = self.ws.recv()
            result = json.loads(message)
            auth_data = result['d'].get('authentication')
            if auth_data and self.password:
                secret = base64.b64encode(hashlib.sha256((self.password + auth_data['salt']).encode('utf-8')).digest())
                auth = base64.b64encode(hashlib.sha256(secret + auth_data['challenge'].encode('utf-8')).digest()).decode('utf-8')
                payload = {
                    "op": 1,
                    "d": {
                        "rpcVersion": 1,
                        "authentication": auth,
                        "eventSubscriptions": 33 | (1 << 14)
                    }
                }
            else:
                payload = {
                    "op": 1,
                    "d": {
                        "rpcVersion": 1,
                        "eventSubscriptions": 33 | (1 << 14)
                    }
                }
            self.ws.send(json.dumps(payload))
            self.ws.recv()  # Identified
            return True
        except Exception as e:
            print(f"Failed to connect/authenticate: {e}")
            return False

    def disconnect(self):
        """Disconnect from OBS WebSocket."""
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def _send_request(self, request_type, request_data=None):
        try:
            request_id = f"req_{int(time.time()*1000)}"
            payload = {
                "op": 6,
                "d": {
                    "requestId": request_id,
                    "requestType": request_type,
                    "requestData": request_data or {}
                }
            }
            self.ws.send(json.dumps(payload)) # type: ignore
            while True:
                message = self.ws.recv() # type: ignore
                response = json.loads(message)
                if response.get('op') == 7 and response.get('d', {}).get('requestId') == request_id:
                    return response.get('d')
        except Exception as e:
            print(f"Error sending request {request_type}: {e}")
            # Mark connection as lost and stop monitoring
            self.running = False
            self._print(f"Lost connection to OBS. Stopping monitor and returning to polling.")
            return None

    def _get_screenshot_hash(self, source_name):
        try:
            response = self._send_request("GetSourceScreenshot", {
                "sourceName": source_name,
                "imageFormat": "png",
                "imageWidth": 320,
                "imageHeight": 180,
                "imageCompressionQuality": 50
            })
            if response and 'responseData' in response:
                image_data = response['responseData']['imageData'].split(',', 1)[1]
                return hashlib.md5(base64.b64decode(image_data)).hexdigest()
            return None
        except Exception as e:
            print(f"Failed to get screenshot for {source_name}: {e}")
            return None

    def _restart_capture(self, source_name):
        try:
            current_time = time.time()
            if current_time - self.last_restart[source_name] < self.cooldown:
                self._print(f"[{source_name}] Skipping restart - cooldown active")
                return False
            self._print(f"[{source_name}] RESTARTING DISPLAY CAPTURE")
            settings_response = self._send_request("GetInputSettings", {"inputName": source_name})
            if not settings_response or 'responseData' not in settings_response:
                self._print(f"[{source_name}] Failed to get source settings")
                return False
            current_settings = settings_response['responseData'].get('inputSettings', {})
            original_type = current_settings.get('type', 0)
            new_type = 1 if original_type == 0 else 0
            self._send_request("SetInputSettings", {"inputName": source_name, "inputSettings": {**current_settings, "type": new_type}})
            time.sleep(0.5)
            response = self._send_request("SetInputSettings", {"inputName": source_name, "inputSettings": {**current_settings, "type": original_type}})
            if response and response.get('requestStatus', {}).get('result'):
                self.last_restart[source_name] = current_time
                self._print(f"[{source_name}] Restart completed")
                return True
            self._print(f"[{source_name}] Restart failed")
            return False
        except Exception as e:
            self._print(f"[{source_name}] Failed to restart capture: {e}")
            return False

    def _now(self):
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _print(self, msg):
        print(f"{self._now()} {msg}")

    async def monitor_all(self):
        """Monitor all sources in a loop."""
        self._print(f"Monitoring sources: {self.source_names}")
        first_run = True
        while self.running:
            for source in self.source_names:
                try:
                    current_hash = await asyncio.to_thread(self._get_screenshot_hash, source)
                    if not self.running:
                        break  # Exit early if connection lost
                    if current_hash is None:
                        self._print(f"[{source}] Could not get screenshot.")
                        continue
                    if current_hash == self.prev_hash[source]:
                        self.identical_count[source] += 1
                        self._print(f"[{source}] Identical frame ({self.identical_count[source]}/{self.threshold})")
                        if self.identical_count[source] >= self.threshold:
                            self._print(f"[{source}] Frozen detected. Restarting...")
                            if self._restart_capture(source):
                                self.identical_count[source] = 0
                                self.prev_hash[source] = self._get_screenshot_hash(source)
                    else:
                        if self.identical_count[source] > 0:
                            self._print(f"[{source}] Frame changed - active")
                        self.identical_count[source] = 0
                    self.prev_hash[source] = current_hash
                except Exception as e:
                    self._print(f"[{source}] Error: {e}")
            if not self.running:
                break  # Exit monitor loop if connection lost
            if first_run:
                first_run = False
            else:
                self.logger.info("Waiting 30 seconds before next round of source checks...")
                await asyncio.sleep(30)  # Wait 30 seconds after the first run
        self.disconnect()
        self._print("Monitor loop exited. Returning to polling.")


def fetch_obs_sources(host, port, password):
    """Fetch all input source names from OBS via WebSocket."""
    try:
        ws = websocket.create_connection(f"ws://{host}:{port}")
        # Receive hello
        hello = json.loads(ws.recv())
        auth_data = hello['d'].get('authentication')
        if auth_data and password:
            secret = base64.b64encode(hashlib.sha256((password + auth_data['salt']).encode('utf-8')).digest())
            auth = base64.b64encode(hashlib.sha256(secret + auth_data['challenge'].encode('utf-8')).digest()).decode('utf-8')
            payload = {
                "op": 1,
                "d": {
                    "rpcVersion": 1,
                    "authentication": auth,
                    "eventSubscriptions": 33 | (1 << 14)
                }
            }
        else:
            payload = {
                "op": 1,
                "d": {
                    "rpcVersion": 1,
                    "eventSubscriptions": 33 | (1 << 14)
                }
            }
        ws.send(json.dumps(payload))
        ws.recv()  # Identified
        # Request input list
        req_id = "fetch_inputs"
        ws.send(json.dumps({
            "op": 6,
            "d": {
                "requestId": req_id,
                "requestType": "GetInputList",
                "requestData": {}
            }
        }))
        while True:
            resp = json.loads(ws.recv())
            if resp.get('op') == 7 and resp['d'].get('requestId') == req_id:
                inputs = resp['d']['responseData']['inputs']
                ws.close()
                return [inp['inputName'] for inp in inputs]
    except Exception as e:
        print(f"Failed to fetch sources from OBS: {e}")
        return []


def is_obs_running(host, port):
    """Check if OBS WebSocket port is open (i.e., OBS is running)."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except Exception:
        return False

async def background_obs_monitor():
    """Background loop: only start monitoring when OBS is running, else poll."""
    poll_interval = 5  # seconds
    while True:
        if is_obs_running(HOST, PORT):
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} OBS detected, starting monitor...")
            obs_sources = fetch_obs_sources(HOST, PORT, PASSWORD)
            if not obs_sources:
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} No sources found in OBS or failed to connect. Retrying...")
                await asyncio.sleep(poll_interval)
                continue
            multi_monitor = OBSMultiSourceMonitor(obs_sources, HOST, PORT, PASSWORD, 1.0, 1, CHECK_INTERVAL)
            if not multi_monitor.connect():
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Failed to connect to OBS for multi-source monitoring. Retrying...")
                await asyncio.sleep(poll_interval)
                continue
            try:
                await multi_monitor.monitor_all()
            except Exception as e:
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Monitor error: {e}")
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} OBS monitoring stopped. Will poll for OBS again...")
        else:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} OBS not running. Polling...")
        await asyncio.sleep(poll_interval)

if __name__ == "__main__":
    asyncio.run(background_obs_monitor())
