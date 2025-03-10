import discord
from discord import app_commands
import os
import subprocess
import json
import asyncio
from dotenv import load_dotenv
from lokbot.util import decode_jwt
import logging
import psutil
import http.server
import threading

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Bot processes dictionary to track running instances
bot_processes = {}

# Discord bot setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="start", description="Start the LokBot with your token")
async def start_bot(interaction: discord.Interaction, token: str):
    user_id = str(interaction.user.id)

    # Check if this user already has a bot running
    if user_id in bot_processes and bot_processes[user_id]["process"].poll(
    ) is None:
        await interaction.response.send_message(
            "You already have a bot running! Stop it first with `/stop`",
            ephemeral=True)
        return

    # Validate token
    try:
        jwt_data = decode_jwt(token)
        if not jwt_data or '_id' not in jwt_data:
            await interaction.response.send_message("Invalid token format",
                                                    ephemeral=True)
            return
    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        await interaction.response.send_message(
            f"Error validating token: {str(e)}", ephemeral=True)
        return

    # Use deferred response with error handling
    try:
        await interaction.response.defer(ephemeral=True)
        interaction_valid = True
    except discord.errors.NotFound:
        interaction_valid = False
        return

    # Start the bot in a subprocess
    try:
        # Create a config for this user
        config_path = f"data/config_{user_id}.json"
        with open("config.json", "r") as f:
            config = json.load(f)
        
        # Add captcha solver config if not present
        if "captcha_solver_config" not in config:
            config["captcha_solver_config"] = {"ttshitu": {"username": "", "password": ""}}

        with open(config_path, "w") as f:
            json.dump(config, f)

        # Log the token length for debugging (without revealing the actual token)
        logger.info(f"Starting bot with token length: {len(token)}")
        
        # Validate token format more thoroughly
        if not token.strip() or len(token) < 50:  # Most JWT tokens are longer
            if interaction_valid:
                await interaction.followup.send("Token appears to be invalid (too short). Please check your token and try again.", ephemeral=True)
            return

        process = subprocess.Popen(["python", "-m", "lokbot", token],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   text=True)

        bot_processes[user_id] = {
            "process": process,
            "token": token,
            "config_path": config_path
        }

        # Send confirmation if interaction is still valid
        if interaction_valid:
            await interaction.followup.send(f"LokBot started successfully! Check your DMs for status updates.",
                                            ephemeral=True)

        # Start log monitoring
        asyncio.create_task(monitor_logs(interaction.user, process))

    except Exception as e:
        logger.error(f"Error starting bot: {str(e)}")
        if interaction_valid:
            await interaction.followup.send(f"Error starting bot: {str(e)}",
                                            ephemeral=True)


@tree.command(name="stop", description="Stop your running LokBot")
async def stop_bot(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    if user_id not in bot_processes:
        await interaction.response.send_message(
            "You don't have a bot running!", ephemeral=True)
        return

    try:
        # Try to defer, but handle the case if interaction has already expired
        try:
            await interaction.response.defer(ephemeral=True)
            interaction_valid = True
        except discord.errors.NotFound:
            # Interaction already timed out or doesn't exist
            interaction_valid = False

        # Terminate the process
        process = bot_processes[user_id]["process"]
        if process.poll() is None:  # Process is still running
            process.terminate()
            try:
                process.wait(timeout=5)  # Wait for process to terminate
            except subprocess.TimeoutExpired:
                process.kill()  # Force kill if needed

        # Send confirmation only if interaction is still valid
        if interaction_valid:
            await interaction.followup.send("LokBot stopped successfully",
                                            ephemeral=True)

        # Clean up
        del bot_processes[user_id]

    except Exception as e:
        logger.error(f"Error stopping bot: {str(e)}")
        if interaction_valid:
            await interaction.followup.send(f"Error stopping bot: {str(e)}",
                                            ephemeral=True)


@tree.command(name="status", description="Check if your LokBot is running")
async def status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    try:
        # Use defer but handle if interaction expired
        try:
            await interaction.response.defer(ephemeral=True)
            interaction_valid = True
        except discord.errors.NotFound:
            # Interaction already timed out
            interaction_valid = False
            return

        if user_id in bot_processes:
            process = bot_processes[user_id]["process"]
            if process.poll() is None:  # Process is still running
                await interaction.followup.send(
                    "Your LokBot is currently running", ephemeral=True)
            else:
                await interaction.followup.send(
                    "Your LokBot process has ended", ephemeral=True)
                del bot_processes[user_id]
        else:
            await interaction.followup.send("You don't have a LokBot running",
                                            ephemeral=True)
    except Exception as e:
        logger.error(f"Error checking status: {str(e)}")
        if interaction_valid:
            await interaction.followup.send(f"Error checking status: {str(e)}",
                                            ephemeral=True)


async def monitor_logs(user, process):
    """Monitor bot status and display only essential status updates"""
    try:
        await user.send("✅ Your LokBot is starting up...")
        
        auth_error_detected = False
        startup_complete = False
        output_buffer = []
        
        # Set subprocess pipes to non-blocking mode
        import fcntl
        import os
        
        # Set stdout to non-blocking
        stdout_fd = process.stdout.fileno()
        fl = fcntl.fcntl(stdout_fd, fcntl.F_GETFL)
        fcntl.fcntl(stdout_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        
        # Set stderr to non-blocking
        stderr_fd = process.stderr.fileno()
        fl = fcntl.fcntl(stderr_fd, fcntl.F_GETFL)
        fcntl.fcntl(stderr_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        
        while True:
            # Check if process has ended
            if process.poll() is not None:
                # Process ended - check if we have an error message
                if not startup_complete and output_buffer:
                    error_message = "❌ LokBot failed to start properly. Possible issues:\n"
                    error_message += "- Invalid or expired token\n"
                    error_message += "- API connection problems\n"
                    error_message += "- Server authentication issues\n\n"
                    error_message += "Check the logs for details and try again with a new token."
                    await user.send(error_message)
                break

            # Try to read output without blocking
            try:
                output = process.stdout.readline()
                if output:
                    stripped_output = output.strip()
                    logger.info(f"LokBot Output: {stripped_output}")
                    
                    # Store recent outputs for error analysis
                    output_buffer.append(stripped_output)
                    if len(output_buffer) > 10:  # Keep only the last 10 messages
                        output_buffer.pop(0)
                    
                    # Check for successful startup
                    if "kingdom/enter" in stripped_output and "result\": true" in stripped_output:
                        if not startup_complete:
                            startup_complete = True
                            await user.send("✅ LokBot has successfully connected to the game server!")
            except (BlockingIOError, IOError):
                # No data available right now, continue
                pass

            # Try to read errors without blocking
            try:
                error = process.stderr.readline()
                if error:
                    stripped_error = error.strip()
                    logger.error(f"LokBot Error: {stripped_error}")
                    
                    # Detect auth errors
                    if "NoAuthException" in stripped_error or "auth/connect" in stripped_error:
                        auth_error_detected = True
                        # Send auth error message
                        await user.send("❌ Authentication failed! Your token appears to be invalid or expired. Please get a new token and try again.")
                        return
                    
                    # Only send critical errors to Discord
                    if "CRITICAL" in stripped_error or "ERROR" in stripped_error or "FATAL" in stripped_error:
                        try:
                            error_message = "❌ Critical error detected. Check logs for details."
                            await user.send(error_message)
                        except discord.errors.HTTPException as e:
                            logger.error(f"Failed to send Discord error message: {str(e)}")
            except (BlockingIOError, IOError):
                # No data available right now, continue
                pass

            # Wait a bit before checking again
            await asyncio.sleep(0.1)

        # Notify when the process has ended
        await user.send("❌ Your LokBot has stopped running.")
    except Exception as e:
        logger.error(f"Error in status monitoring: {str(e)}")
        try:
            # Use a shorter message to avoid potential Discord issues
            await user.send("❌ Error monitoring LokBot status. Check server logs for details.")
        except:
            logger.error("Failed to send error message to user")


@client.event
async def on_ready():
    await tree.sync()
    logger.info(f"Discord bot is ready! Logged in as {client.user}")


def run_http_server():
    """Run a simple HTTP server to keep the bot alive"""

    class SimpleHTTPRequestHandler(http.server.BaseHTTPRequestHandler):

        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'LokBot is running\n')

        def do_HEAD(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()

    # Use the PORT environment variable provided by Render, default to 10000 as detected
    port = int(os.environ.get('PORT', 10000))
    server = http.server.HTTPServer(('0.0.0.0', port),
                                    SimpleHTTPRequestHandler)

    # Start server in a separate thread
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    logger.info(f"HTTP server started on port {port}")


def run_discord_bot():
    # Get the token from environment variable
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("Error: DISCORD_BOT_TOKEN not found in environment")
        return

    # Start HTTP server to keep the bot alive
    run_http_server()

    try:
        logger.info(f"Starting Discord bot at port {os.environ.get('PORT', 10000)}")
        # Check token and API connectivity
        if not token:
            logger.error("ERROR: DISCORD_BOT_TOKEN not provided")
            # Keep server running even with invalid token
            import time
            while True:
                time.sleep(60)
                logger.info("HTTP server still alive, waiting for valid token...")
                
        # Run the Discord bot
        client.run(token)
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Discord bot crashed: {str(e)}")
        # Print full exception details
        import traceback
        traceback.print_exc()
        
        # Keep the HTTP server running even if the bot crashes
        import time
        while True:
            time.sleep(60)
            logger.info("HTTP server still alive despite bot crash, waiting for restart...")


if __name__ == "__main__":
    run_discord_bot()
