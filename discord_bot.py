import discord
from discord import app_commands
import os
import subprocess
import json
import signal
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from lokbot.util import decode_jwt
from lokbot.app import main

# Load environment variables
load_dotenv()

# Simple HTTP server for keeping the bot alive
class KeepAliveServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Discord Bot is running\n')

def run_keep_alive_server(port=3001):
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, KeepAliveServer)
    print(f"Starting Discord Bot HTTP server on port {port}")
    httpd.serve_forever()

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
    if user_id in bot_processes and bot_processes[user_id]["process"].poll() is None:
        await interaction.response.send_message("You already have a bot running! Stop it first with `/stop`", ephemeral=True)
        return

    # Validate token
    try:
        jwt_data = decode_jwt(token)
        if not jwt_data or '_id' not in jwt_data:
            await interaction.response.send_message("Invalid token format", ephemeral=True)
            return
    except Exception as e:
        await interaction.response.send_message(f"Error validating token: {str(e)}", ephemeral=True)
        return

    # Use deferred response with error handling
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        interaction_valid = True
    except (discord.errors.NotFound, discord.errors.HTTPException):
        interaction_valid = False
        return

    # Start the bot in a subprocess
    try:
        # Create a config for this user
        config_path = f"data/config_{user_id}.json"
        with open("config.json", "r") as f:
            config = json.load(f)

        with open(config_path, "w") as f:
            json.dump(config, f)

        # Set token in environment variable which is how the module expects it
        my_env = os.environ.copy()
        my_env["AUTH_TOKEN"] = token
        
        # Make sure data directory exists
        os.makedirs("data", exist_ok=True)
        
        # Create a helper script to run LokBot with full error logging
        helper_script = "data/run_lokbot.py"
        with open(helper_script, "w") as f:
            f.write("""
import os
import sys
import traceback

# Add current directory to path
sys.path.insert(0, '.')

try:
    from lokbot.app import main
    print("Starting LokBot with token from environment variable")
    if os.environ.get("AUTH_TOKEN"):
        print(f"Token found in environment: {os.environ.get('AUTH_TOKEN')[:10]}...")
        main()
    else:
        print("ERROR: No AUTH_TOKEN found in environment variables")
except Exception as e:
    print(f"CRITICAL ERROR in LokBot: {str(e)}")
    traceback.print_exc()
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python path: {sys.path}")
    print(f"Environment variables: {dict(os.environ)}")
""")
        
        # Run the helper script with proper environment and working directory
        process = subprocess.Popen(
            ["python", helper_script], 
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=my_env,
            cwd=os.getcwd()  # Ensure correct working directory
        )

        bot_processes[user_id] = {
            "process": process,
            "token": token,
            "config_path": config_path
        }

        # Send confirmation if interaction is still valid
        if interaction_valid:
            await interaction.followup.send(f"LokBot started successfully!", ephemeral=True)

        # Start log monitoring
        asyncio.create_task(monitor_logs(interaction.user, process))

    except Exception as e:
        if interaction_valid:
            await interaction.followup.send(f"Error starting bot: {str(e)}", ephemeral=True)
        print(f"Error starting bot: {str(e)}")

@tree.command(name="stop", description="Stop your running LokBot")
async def stop_bot(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    if user_id not in bot_processes:
        await interaction.response.send_message("You don't have a bot running!", ephemeral=True)
        return

    try:
        # Try to defer, but handle the case if interaction has already expired
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            interaction_valid = True
        except (discord.errors.NotFound, discord.errors.HTTPException):
            # Interaction already timed out, doesn't exist, or already acknowledged
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
            await interaction.followup.send("LokBot stopped successfully", ephemeral=True)

        # Clean up
        del bot_processes[user_id]

    except Exception as e:
        if interaction_valid:
            await interaction.followup.send(f"Error stopping bot: {str(e)}", ephemeral=True)
        print(f"Error stopping bot: {str(e)}")

@tree.command(name="status", description="Check if your LokBot is running")
async def status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    try:
        # Use defer but handle if interaction expired
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            interaction_valid = True
        except (discord.errors.NotFound, discord.errors.HTTPException):
            # Interaction already timed out or already acknowledged
            interaction_valid = False
            return

        if user_id in bot_processes:
            process = bot_processes[user_id]["process"]
            if process.poll() is None:  # Process is still running
                await interaction.followup.send("Your LokBot is currently running", ephemeral=True)
            else:
                await interaction.followup.send("Your LokBot process has ended", ephemeral=True)
                del bot_processes[user_id]
        else:
            await interaction.followup.send("You don't have a LokBot running", ephemeral=True)
    except Exception as e:
        if interaction_valid:
            await interaction.followup.send(f"Error checking status: {str(e)}", ephemeral=True)
        print(f"Error checking status: {str(e)}")

async def monitor_logs(user, process):
    """Monitor bot status and display application logs"""
    try:
        debug_info = []
        await user.send("✅ Your LokBot has started successfully!")
        
        # Create a task to continuously read and display output
        async def read_output_continuously():
            nonlocal debug_info
            while process.poll() is None:  # While process is still running
                try:
                    # Read line from stdout (non-blocking)
                    if process.stdout:
                        line = await asyncio.get_event_loop().run_in_executor(None, process.stdout.readline)
                        if line:
                            line_text = line.strip().decode('utf-8', errors='replace') \
                                if isinstance(line, bytes) else line.strip()
                            
                            # Print to Replit console
                            print(f"[LokBot] {line_text}")
                            
                            # Collect debug info
                            debug_info.append(line_text)
                            
                            # Send all log messages to improve visibility during debugging
                            # (we can make this more selective later)
                            try:
                                if len(line_text) > 0:  # Only send non-empty lines
                                    await user.send(f"📋 **Log**: {line_text}")
                            except:
                                pass  # Ignore if can't send to user
                            
                            # Send alerts for errors
                            if "ERROR" in line_text or "CRITICAL" in line_text or "Exception" in line_text:
                                try:
                                    await user.send(f"⚠️ **Alert**: {line_text}")
                                except:
                                    pass  # Ignore if can't send to user
                except Exception as read_err:
                    print(f"Error reading output: {str(read_err)}")
                
                # Small delay to avoid high CPU usage
                await asyncio.sleep(0.1)
        
        # Start reading output in the background
        output_task = asyncio.create_task(read_output_continuously())
        
        # Wait for process to complete
        while process.poll() is None:
            await asyncio.sleep(1)
            
        # Cancel the output reading task when process ends
        output_task.cancel()
            
        # Notify when the process has ended
        await user.send("❌ Your LokBot has stopped running.")
    except Exception as e:
        print(f"Error in status monitoring: {str(e)}")

@client.event
async def on_ready():
    await tree.sync()
    print(f"Discord bot is ready! Logged in as {client.user}")

def run_discord_bot():
    # Get the token from environment variable
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("Error: DISCORD_BOT_TOKEN not found in environment")
        return

    client.run(token)

if __name__ == "__main__":
    # Start HTTP server in a separate thread
    port = int(os.getenv("DISCORD_BOT_PORT", 3001))
    http_thread = threading.Thread(target=run_keep_alive_server, args=(port,), daemon=True)
    http_thread.start()
    print(f"Discord Bot HTTP server started on port {port}")
    
    # Run Discord bot in main thread
    run_discord_bot()