#!/bin/bash

# OBS Capture Monitor Setup Script
# This script helps install and manage the OBS Capture Monitor as a macOS Launch Agent

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_FILE="com.user.obs-capture-monitor.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
SERVICE_NAME="com.user.obs-capture-monitor"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

setup_log_directory() {
    print_status "Setting up log directory..."
    
    LOG_DIR="/var/log/obs_capture_monitor"
    
    if [ ! -d "$LOG_DIR" ]; then
        print_status "Creating log directory: $LOG_DIR"
        sudo mkdir -p "$LOG_DIR"
        sudo chown "$USER:wheel" "$LOG_DIR"
        sudo chmod 755 "$LOG_DIR"
    fi
    
    # Create log files if they don't exist
    for logfile in "obs_capture_monitor.log" "obs_capture_monitor_error.log"; do
        if [ ! -f "$LOG_DIR/$logfile" ]; then
            print_status "Creating log file: $LOG_DIR/$logfile"
            sudo touch "$LOG_DIR/$logfile"
            sudo chown "$USER:wheel" "$LOG_DIR/$logfile"
            sudo chmod 664 "$LOG_DIR/$logfile"
        fi
    done
}

install_service() {
    print_status "Installing OBS Capture Monitor service..."
    
    # Create LaunchAgents directory if it doesn't exist
    mkdir -p "$LAUNCH_AGENTS_DIR"
    
    # Copy plist file to LaunchAgents directory
    cp "$SCRIPT_DIR/$PLIST_FILE" "$LAUNCH_AGENTS_DIR/"
    
    # Load the service
    launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_FILE"
    
    print_status "Service installed and loaded successfully!"
    print_status "The service will now start automatically at login."
}

uninstall_service() {
    print_status "Uninstalling OBS Capture Monitor service..."
    
    # Unload the service
    launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_FILE" 2>/dev/null || true
    
    # Remove plist file
    rm -f "$LAUNCH_AGENTS_DIR/$PLIST_FILE"
    
    print_status "Service uninstalled successfully!"
}

start_service() {
    print_status "Starting OBS Capture Monitor service..."
    launchctl start "$SERVICE_NAME"
    print_status "Service started!"
}

stop_service() {
    print_status "Stopping OBS Capture Monitor service..."
    launchctl stop "$SERVICE_NAME"
    print_status "Service stopped!"
}

restart_service() {
    print_status "Restarting OBS Capture Monitor service..."
    launchctl stop "$SERVICE_NAME" 2>/dev/null || true
    sleep 2
    launchctl start "$SERVICE_NAME"
    print_status "Service restarted!"
}

check_status() {
    print_status "Checking service status..."
    
    if launchctl list | grep -q "$SERVICE_NAME"; then
        print_status "✅ Service is loaded"
        
        # Get PID if running
        PID=$(launchctl list | grep "$SERVICE_NAME" | awk '{print $1}')
        if [ "$PID" != "-" ] && [ -n "$PID" ]; then
            print_status "✅ Service is running (PID: $PID)"
        else
            print_warning "⚠️  Service is loaded but not running"
        fi
    else
        print_error "❌ Service is not loaded"
    fi
}

show_logs() {
    print_status "Showing recent logs..."
    echo "=== Standard Output ==="
    tail -n 20 /var/log/obs_capture_monitor/obs_capture_monitor.log 2>/dev/null || echo "No standard output logs found"
    echo
    echo "=== Error Output ==="
    tail -n 20 /var/log/obs_capture_monitor/obs_capture_monitor_error.log 2>/dev/null || echo "No error logs found"
}

show_help() {
    echo "OBS Capture Monitor Setup Script"
    echo
    echo "Usage: $0 [command]"
    echo
    echo "Commands:"
    echo "  install     Install and start the service"
    echo "  uninstall   Stop and remove the service"
    echo "  start       Start the service"
    echo "  stop        Stop the service"
    echo "  restart     Restart the service"
    echo "  status      Check service status"
    echo "  logs        Show recent logs"
    echo "  help        Show this help message"
    echo
    echo "The service will automatically start at login once installed."
}

# Main script logic
case "${1:-help}" in
    install)
        setup_log_directory
        install_service
        ;;
    uninstall)
        uninstall_service
        ;;
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    status)
        check_status
        ;;
    logs)
        show_logs
        ;;
    help|*)
        show_help
        ;;
esac
