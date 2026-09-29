import { formatMention } from "@/utils/mentions";

export type WorkplaceSuggestion = {
  label: string;
  /** One short line beside the label: what picking the row gets you. */
  hint: string;
  /**
   * The prompt put into the composer. Absent on setup rows, which link to where
   * the thing is set up instead of asking the agent for it. May carry an agent
   * mention in storage form, @[id:name].
   */
  text?: string;
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
  /** The catalog's own line about the channel, when it has one. */
  description?: string | null;
};

export type WorkspaceShape = {
  /** Channels already wired up, named and drawn by the catalog. */
  connectedChannels: ChannelOption[];
  /** Messaging channels the catalog offers that nothing uses yet. */
  availableChannels: ChannelOption[];
  mcpCount: number;
  skillCount: number;
  agents: { id: string; name: string }[];
};

export type SuggestionCopyKey =
  | "putOnChannel.label"
  | "putOnChannel.hint"
  | "connectTool.label"
  | "connectTool.hint"
  | "teachSkill.label"
  | "teachSkill.hint"
  | "catchUp.label"
  | "catchUp.hint"
  | "catchUp.text"
  | "tryTool.label"
  | "tryTool.hint"
  | "tryTool.text"
  | "askAgent.label"
  | "askAgent.hint"
  | "askAgent.text";

/**
 * The words for each row, looked up by key under `Workplace.suggestions`. The
 * server hands in next-intl's translator; this module only decides which rows
 * there are.
 */
export type SuggestionCopy = (
  key: SuggestionCopyKey,
  values?: Record<string, string>
) => string;

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
  copy: SuggestionCopy,
  max = 4
): WorkplaceSuggestion[] {
  const setup: WorkplaceSuggestion[] = [];
  const prompts: WorkplaceSuggestion[] = [];

  if (shape.connectedChannels.length === 0) {
    // Named from the catalog, so a deployment that ships Slack but not
    // Telegram offers Slack instead of advertising something it cannot do.
    for (const channel of shape.availableChannels.slice(0, 2)) {
      setup.push({
        label: copy("putOnChannel.label", { channel: channel.name }),
        hint: channel.description?.trim() || copy("putOnChannel.hint"),
        href: "/triggers/create",
        iconUrl: channel.iconUrl,
      });
    }
  }

  if (shape.mcpCount === 0) {
    setup.push({
      label: copy("connectTool.label"),
      hint: copy("connectTool.hint"),
      href: "/connections",
    });
  }

  if (shape.skillCount === 0) {
    setup.push({
      label: copy("teachSkill.label"),
      hint: copy("teachSkill.hint"),
      href: "/skills",
    });
  }

  for (const channel of shape.connectedChannels.slice(0, 2)) {
    prompts.push({
      label: copy("catchUp.label", { channel: channel.name }),
      hint: copy("catchUp.hint"),
      text: copy("catchUp.text", { channel: channel.name }),
      iconUrl: channel.iconUrl,
    });
  }

  if (shape.mcpCount > 0) {
    prompts.push({
      label: copy("tryTool.label"),
      hint: copy("tryTool.hint"),
      text: copy("tryTool.text"),
    });
  }

  const [firstAgent] = shape.agents;
  if (firstAgent) {
    prompts.push({
      label: copy("askAgent.label", { agent: firstAgent.name }),
      hint: copy("askAgent.hint"),
      // A real mention, as if picked from the @ menu, so the question is
      // addressed to that agent rather than just naming it.
      text: copy("askAgent.text", {
        agent: formatMention(firstAgent.id, firstAgent.name),
      }),
    });
  }

  // Setup first while the workspace is bare, so the empty state points at the
  // thing that makes everything else work.
  return [...setup, ...prompts].slice(0, max);
}
