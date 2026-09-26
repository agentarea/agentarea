export type WorkplaceSuggestion = {
  label: string;
  text: string;
  /** Set when the suggestion is something to go and set up, not something to ask. */
  href?: string;
  /**
   * The channel's own logo, as the catalog resolved it. Nothing here maps a
   * channel to a picture: which channels exist grows by configuration, and a
   * hard-coded logo would be wrong for every channel the map never heard of.
   */
  iconUrl?: string | null;
};

export type ChannelOption = {
  id: string;
  name: string;
  iconUrl?: string | null;
};

export type WorkspaceShape = {
  /** Channels already wired up, named and drawn by the catalog. */
  connectedChannels: ChannelOption[];
  /** Messaging channels the catalog offers that nothing uses yet. */
  availableChannels: ChannelOption[];
  mcpCount: number;
  skillCount: number;
  agentNames: string[];
};

/**
 * What to offer on an empty workplace.
 *
 * The four chips here used to be fixed copy — "Generate documentation",
 * "Debug issue" — which described a coding assistant rather than this
 * workspace, and stayed identical whether or not anything was connected. These
 * are derived instead: what is missing becomes something to set up, what
 * exists becomes something to ask about, and both carry the real logo so you
 * can see what you are about to start.
 */
export function buildWorkplaceSuggestions(
  shape: WorkspaceShape,
  max = 4
): WorkplaceSuggestion[] {
  const setup: WorkplaceSuggestion[] = [];
  const prompts: WorkplaceSuggestion[] = [];

  if (shape.connectedChannels.length === 0) {
    // Named from the catalog, so a deployment that ships Slack but not
    // Telegram offers Slack instead of advertising something it cannot do.
    for (const channel of shape.availableChannels.slice(0, 2)) {
      setup.push({
        label: `Put an agent on ${channel.name}`,
        text: `Answer where people already are — connect ${channel.name} and pick the agent that replies`,
        href: "/triggers/create",
        iconUrl: channel.iconUrl,
      });
    }
  }

  if (shape.mcpCount === 0) {
    setup.push({
      label: "Connect a tool",
      text: "Give agents an MCP server — Google, GitHub, your own API",
      href: "/connections",
    });
  }

  if (shape.skillCount === 0) {
    setup.push({
      label: "Teach a skill",
      text: "Package a procedure once and let every agent reuse it",
      href: "/skills",
    });
  }

  for (const channel of shape.connectedChannels.slice(0, 2)) {
    prompts.push({
      label: `Catch up on ${channel.name}`,
      text: `Summarise what came in on ${channel.name} today and flag anything that needs an answer`,
      iconUrl: channel.iconUrl,
    });
  }

  if (shape.mcpCount > 0) {
    prompts.push({
      label: "Try a connected tool",
      text: "List the tools you can reach right now and what each one is for",
    });
  }

  const [firstAgent] = shape.agentNames;
  if (firstAgent) {
    prompts.push({
      label: `Ask ${firstAgent}`,
      text: `${firstAgent}, what are you set up to do and what access do you have?`,
    });
  }

  // Setup first while the workspace is bare, so the empty state points at the
  // thing that makes everything else work.
  return [...setup, ...prompts].slice(0, max);
}
