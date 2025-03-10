
# LokBot

A bot for automating activities in a game called "Lok" or "Lord of Knights".

## Discord Bot Integration

This project includes a Discord bot that allows you to control the LokBot through Discord commands.

### Setup

1. Create a Discord bot in the [Discord Developer Portal](https://discord.com/developers/applications)
2. Enable the "Message Content Intent" under the Bot section
3. Copy your bot token and add it to the `.env` file
4. Invite the bot to your server with appropriate permissions (bot, applications.commands)

### Commands

- `/start <token>` - Start the LokBot with your game token
- `/stop` - Stop your running LokBot instance
- `/status` - Check if your LokBot is running

### Running the Discord Bot

```
python discord_bot.py
```

## Original LokBot Usage

If you prefer to run LokBot directly without Discord:

```
python -m lokbot your_token_here
```

## License

This project is MIT licensed.
