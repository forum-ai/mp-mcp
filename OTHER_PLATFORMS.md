# Installation on other platforms

Steps for connecting the Materials Project to apps not covered in the [README](README.md). You need your Materials Project API key first; the README's "Before you start" section shows how to get one.

These steps follow each app's own documentation but have not been tried yet. If one fails, please [open an issue](https://github.com/forum-ai/mp-mcp/issues) and say which app and which step.

## VS Code (not yet tried)

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

## Cursor (not yet tried)

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
