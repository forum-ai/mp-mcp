# Materials Project for your AI assistant

Connect an AI app to the [Materials Project](https://materialsproject.org) and ask about its data in plain language. The app can look up properties of known materials, find materials that meet your criteria, and fetch band structures, phonons, phase diagrams and crystal structure files. Each answer names the Materials Project ID of every material it used, so you can check it on the website.

**Which apps work.** Claude Code works today; it is Anthropic's assistant that runs in a terminal window. Codex, Gemini CLI, Antigravity, VS Code and Cursor have steps below, but those steps have not been tried yet. If one fails, please [open an issue](https://github.com/forum-ai/mp-mcp/issues). The chat in the Claude desktop app, claude.ai in a browser and ChatGPT can't be connected yet.

## Before you start: get your free API key

An API key is a personal code that lets an app use your Materials Project account.

1. Go to <https://next-gen.materialsproject.org/api> and log in. If you don't have an account yet, that page lets you create one for free.
2. Copy the key shown on that page, and keep the page open until you have pasted the key into your app.

Treat the key like a password and don't share it.

## Connect it

Find your app below and follow its steps in order. Each section also shows how to remove it again.

### Claude Code

**Add it**

1. **In a terminal**, start Claude Code:

   ```bash
   claude
   ```

2. **In Claude Code**, type these two commands, one at a time. The first adds the FORUM-AI plugin list (Claude Code calls it a marketplace); the second installs the Materials Project plugin from it.

   ```
   /plugin marketplace add forum-ai/mp-mcp
   ```

   ```
   /plugin install mp-mcp@forum-ai-mp-mcp
   ```

3. **In Claude Code**, a box asks for your API key. Paste it and press Enter. Claude Code stores it in your computer's password store.

**Remove it**

1. **In a terminal** (not inside Claude Code), run:

   ```bash
   claude plugin uninstall mp-mcp@forum-ai-mp-mcp
   ```

2. Optional: to remove the FORUM-AI plugin list as well, run this too:

   ```bash
   claude plugin marketplace remove forum-ai-mp-mcp
   ```

### Codex (not yet tried)

**Add it**

1. **In a terminal**, add the FORUM-AI plugin list:

   ```bash
   codex plugin marketplace add forum-ai/mp-mcp
   ```

2. **In Codex**, type `/plugins`. In the list that opens, choose **Materials Project** and install it.
3. **In Codex**, paste your API key when asked.

**Remove it**

1. **In Codex**, type `/plugins`, choose **Materials Project**, and uninstall it.
2. Optional, **in a terminal**: remove the FORUM-AI plugin list as well:

   ```bash
   codex plugin marketplace remove forum-ai-mp-mcp
   ```

### Gemini CLI (not yet tried)

**Add it**

1. **In a terminal**, run:

   ```bash
   gemini extensions install https://github.com/forum-ai/mp-mcp
   ```

2. **In the same terminal**, paste your API key when asked.
3. Close Gemini CLI if it is open, and start it again.

**Remove it**

1. **In a terminal**, run:

   ```bash
   gemini extensions uninstall mp-mcp
   ```

### Antigravity (not yet tried)

**Add it**

1. **In a terminal**, run:

   ```bash
   agy plugin install https://github.com/forum-ai/mp-mcp
   ```

   The plugin arrives switched off.

2. **In Antigravity**, type `/plugin` and turn on **Materials Project**. (In the Antigravity app, the same switch is under Customizations → Installed.)
3. **In Antigravity**, paste your API key when asked.

**Remove it**

1. **In a terminal**, run:

   ```bash
   agy plugin uninstall mp-mcp
   ```

### VS Code (not yet tried)

**Add it**

1. **In VS Code**, open the Command Palette (Cmd+Shift+P on a Mac, Ctrl+Shift+P on Windows and Linux) and run **MCP: Open User Configuration**. A settings file opens.
2. **In that file**, if it is empty, paste the block below as it is. If it already has a `"servers"` section, copy only the `"materials-project"` part into that section, and the `"inputs"` part beside it.

   ```json
   {
     "inputs": [
       { "type": "promptString", "id": "mp-api-key", "description": "Materials Project API key", "password": true }
     ],
     "servers": {
       "materials-project": {
         "type": "http",
         "url": "https://mp.forum-ai.org/mcp",
         "headers": { "X-API-KEY": "${input:mp-api-key}" }
       }
     }
   }
   ```

3. **In VS Code**, save the file. The first time the Materials Project tools start, VS Code asks for your API key; paste it.

**Remove it**

1. **In VS Code**, open the Command Palette, run **MCP: List Servers**, choose **materials-project**, and uninstall it.
2. If it is still listed, open the same file as in step 1 above and delete the `"materials-project"` part.

### Cursor (not yet tried)

**Add it**

1. **In Cursor**, open the file `.cursor/mcp.json` in your home folder. If it doesn't exist, create it.
2. **In that file**, paste the block below, then replace `YOUR_MP_KEY` with your API key. Keep the quote marks around it.

   ```json
   {
     "mcpServers": {
       "materials-project": {
         "url": "https://mp.forum-ai.org/mcp",
         "headers": { "X-API-KEY": "YOUR_MP_KEY" }
       }
     }
   }
   ```

3. **In Cursor**, save the file.

**Remove it**

1. **In Cursor**, open the same file and delete the `"materials-project"` part, then save it.

## Try it

Ask these in the app you just connected, in your own words if you like:

- "What is the band gap of GaN, and is it direct?"
- "Find stable lithium-containing oxides with a band gap between 2 and 4 eV, ranked by how stable they are."
- "Show me silicon's phonon band structure. Are there any unstable modes?"
- "Give me a CIF file of the conventional cell of rutile TiO2."

## Your key and your data

Each question goes, with your key, to the FORUM-AI team's server at `mp.forum-ai.org`. The server passes it to the Materials Project and keeps no copy of your key. It can only read Materials Project data; it can't change anything in your account.

## If something goes wrong

- **The app says it "needs your Materials Project API key".** The key is missing or mistyped. In Claude Code, type `/plugin`, open **Installed**, choose **Materials Project**, and enter the key again under its options.
- **The app doesn't seem to know about the Materials Project.** Quit the app and open it again. In Claude Code, type `/mcp`: `plugin:mp-mcp:materials-project` should be in the list, marked connected.
- **An answer names no Materials Project IDs.** Ask the app to "use the Materials Project tools" and ask again.
- **A step above doesn't work in your app:** [open an issue](https://github.com/forum-ai/mp-mcp/issues) and say which app and which step.

## For developers

[DEPLOY.md](DEPLOY.md) covers the tools in detail, running the server on your own computer, deploying it, releasing new plugin versions, and development.
