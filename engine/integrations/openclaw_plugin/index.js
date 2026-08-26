import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import {
  PLUGIN_ID,
  TOKEN_ENV,
  createMnoOpenClawMemoryAdapter,
  parseMnoOpenClawConfig,
} from "./runtime.js";

export { PLUGIN_ID, TOKEN_ENV, createMnoOpenClawMemoryAdapter, parseMnoOpenClawConfig } from "./runtime.js";

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "MNO OpenClaw Memory",
  register(api) {
    const config = parseMnoOpenClawConfig(api.pluginConfig || {});
    if (!config) {
      api.logger?.warn?.("[mno-openclaw] disabled: invalid plugin configuration");
      return;
    }
    const adapter = createMnoOpenClawMemoryAdapter({
      config,
      token: process.env[TOKEN_ENV] || "",
      logger: api.logger,
    });
    api.on("before_prompt_build", (event, ctx) => adapter.beforePromptBuild(event, ctx), {
      timeoutMs: config.contextTimeoutMs,
    });
    api.on("agent_end", (event, ctx) => {
      adapter.agentEnd(event, ctx);
    }, { timeoutMs: 100 });
    api.on("gateway_stop", () => adapter.close(), { timeoutMs: 100 });
  },
});
