# OBS Capture Monitor

A Python service that automatically monitors and restarts frozen capture sources in OBS Studio using the WebSocket API.

## Features

- **Automatic Detection**: Monitors all capture sources for frozen/stuck frames
- **Smart Restart**: Automatically restarts frozen sources by toggling capture settings
- **Background Service**: Runs continuously in the background on macOS
- **Multi-Source Support**: Monitors all sources simultaneously with a single WebSocket connection
- **Auto-Discovery**: Automatically detects when OBS starts/stops and adapts accordingly
- **macOS Integration**: Includes Launch Agent for automatic startup at login

## Requirements

- Python 3.7+
- OBS Studio with WebSocket plugin enabled
- `websocket-client` library

## Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd obs_capture_monitor
```

1. Install dependencies:

```bash
pip install -r requirements.txt
```

1. Configure OBS WebSocket:
   - In OBS: Tools → WebSocket Server Settings
      - Enable server on port 4455
      - Generate, copy and and 
2. Set `PASSWORD` in the script

## Usage

### Manual Run

Run the service manually:

```bash
python obs_capture_monitor_service.py
```

This may fail due to missing log location - just follow the instructions.

### Install as macOS Service (Recommended)

To automatically start the service at login, use the setup script:

```bash
# Make the setup script executable (if not already)
chmod +x setup_service.sh

# Install and start the service
./setup_service.sh install
```

The service will now start automatically when you log in to macOS.

### Service Management

Use the setup script to manage the service:

```bash
# Check service status
./setup_service.sh status

# Start the service
./setup_service.sh start

# Stop the service
./setup_service.sh stop

# Restart the service
./setup_service.sh restart

# View recent logs
./setup_service.sh logs

# Uninstall the service
./setup_service.sh uninstall
```

### What the Service Does

The service will:

- Poll for OBS every 5 seconds when not running
- Auto-discover and monitor all capture sources when OBS is detected
- Log activity to `/var/log/obs_capture_monitor/obs_capture_monitor.log`

## Configuration

Edit the script constants to customize:

- `HOST`: OBS WebSocket host (default: localhost)
- `PORT`: OBS WebSocket port (default: 4455)
- `PASSWORD`: WebSocket password
- Monitor intervals and thresholds in the monitoring loop

## Log Files

When running as a service, logs are written to:

- Standard output: `/var/log/obs_capture_monitor/obs_capture_monitor.log`
- Error output: `/var/log/obs_capture_monitor/obs_capture_monitor_error.log`

## Troubleshooting

### Python Environment Issues

If you see "websocket-client not installed" when running as a service, the Launch Agent may be using a different Python environment. The setup script automatically detects your Python path, but if issues persist:

1. Check your Python path: `which python3`
2. Ensure websocket-client is installed: `pip install websocket-client`
3. Update the plist file to use the correct Python path if needed

## Credits

Inspired by [yayuanli's OBS_Restart_Capture_Stuck_Source](https://github.com/yayuanli/OBS_Restart_Capture_Stuck_Source).
