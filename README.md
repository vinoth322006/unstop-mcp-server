# Unstop MCP Server 🚀

Hey there! Welcome to the Unstop MCP Server. 

I built this project to act as a bridge between the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) and Unstop's platform. Essentially, this server gives your favorite AI assistants (like Claude Desktop or Cursor) the "hands" and "eyes" to discover contests, track user participation, and pull analytics directly from Unstop.

*(Note: Since there isn't an official public API for Unstop just yet, this project currently runs on some mocked data to demonstrate how the integration would work perfectly in the real world!)*

## What can it do?
Once connected to your AI, it can do things like:
- **Discover Contests**: Filter through open hackathons, coding challenges, and designathons.
- **Track Participation**: Check up on a specific user to see what they've registered for.
- **Pull Analytics**: Grab average scores and participant counts for a specific contest.
- **Read the Rules**: The AI can literally read the platform rules before helping you out.

## How to get it running
It's super simple to spin up locally on your machine.

1. **Clone the repo** and hop into the directory.
2. **Set up a virtual environment** (optional but highly recommended!):
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On Mac/Linux:
   source venv/bin/activate
   ```
3. **Install the requirements**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Run the server!**:
   ```bash
   python run.py
   ```

By default, it runs using `stdio` (which is exactly what local AI apps want). If you want to run it over a web server instead, just run `python run.py --transport sse`.

## Connecting to Claude Desktop
If you use Claude Desktop, you can plug this right in. Just copy the JSON from `claude_desktop_config.json` and paste it into your Claude configuration file (usually located at `%APPDATA%\Claude\claude_desktop_config.json` on Windows). 

Restart Claude, and you'll see a neat little hammer icon showing your new Unstop tools!

---
Feel free to poke around the code in `tools.py` if you want to add your own features. Happy coding! 🎉
