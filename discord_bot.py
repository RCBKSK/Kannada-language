
import discord
from discord import app_commands
import os
import subprocess
import json
import signal
import asyncio
from dotenv import load_dotenv
from lokbot.util import decode_jwt
from lokbot.app import main

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
    
    # Use deferred response since starting might take more than 3 seconds
    await interaction.response.defer(ephemeral=True)
    
    # Start the bot in a subprocess
    try:
        # Create a config for this user
        config_path = f"data/config_{user_id}.json"
        with open("config.json", "r") as f:
            config = json.load(f)
        
        with open(config_path, "w") as f:
            json.dump(config, f)
        
        process = subprocess.Popen(["python", "-m", "lokbot", token], 
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,
                                  text=True)
        
        bot_processes[user_id] = {
            "process": process,
            "token": token,
            "config_path": config_path
        }
        
        # Send confirmation
        await interaction.followup.send(f"LokBot started successfully!", ephemeral=True)
        
        # Start log monitoring
        asyncio.create_task(monitor_logs(interaction.user, process))
        
    except Exception as e:
        await interaction.followup.send(f"Error starting bot: {str(e)}", ephemeral=True)

@tree.command(name="stop", description="Stop your running LokBot")
async def stop_bot(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    if user_id not in bot_processes:
        await interaction.response.send_message("You don't have a bot running!", ephemeral=True)
        return
    
    # Use deferred response since stopping might take more than 3 seconds
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Terminate the process
        process = bot_processes[user_id]["process"]
        if process.poll() is None:  # Process is still running
            process.terminate()
            try:
                process.wait(timeout=5)  # Wait for process to terminate
            except subprocess.TimeoutExpired:
                process.kill()  # Force kill if needed
                
        await interaction.followup.send("LokBot stopped successfully", ephemeral=True)
        
        # Clean up
        del bot_processes[user_id]
        
    except Exception as e:
        await interaction.followup.send(f"Error stopping bot: {str(e)}", ephemeral=True)

@tree.command(name="status", description="Check if your LokBot is running")
async def status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    
    # Use defer for consistency, even though this is usually quick
    await interaction.response.defer(ephemeral=True)
    
    if user_id in bot_processes:
        process = bot_processes[user_id]["process"]
        if process.poll() is None:  # Process is still running
            await interaction.followup.send("Your LokBot is currently running", ephemeral=True)
        else:
            await interaction.followup.send("Your LokBot process has ended", ephemeral=True)
            del bot_processes[user_id]
    else:
        await interaction.followup.send("You don't have a LokBot running", ephemeral=True)

async def monitor_logs(user, process):
    """Monitor and send process logs to user via DM"""
    for line in iter(process.stdout.readline, ''):
        if not line:
            break
        
        # Filter sensitive info from logs
        filtered_line = line
        
        # Only send important log messages to avoid spam
        if "ERROR" in line or "WARNING" in line or "INFO" in line:
            try:
                await user.send(f"```{filtered_line[:1900]}```")  # Discord message limit
            except:
                pass  # User might have DMs disabled

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
    run_discord_bot()
