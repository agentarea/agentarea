/**
 * Utilities for handling @ mentions in text input
 */

export interface MentionPosition {
  atIndex: number;
  query: string;
  textBeforeCursor: string;
}

/**
 * Find the last @ mention position in text before cursor
 */
export function findMentionPosition(
  text: string,
  cursorPosition: number
): MentionPosition | null {
  const textBeforeCursor = text.substring(0, cursorPosition);
  
  // Find all @ symbols before cursor
  const atIndices: number[] = [];
  for (let i = textBeforeCursor.length - 1; i >= 0; i--) {
    if (textBeforeCursor[i] === '@') {
      atIndices.push(i);
    }
  }

  if (atIndices.length === 0) {
    return null;
  }

  // Check each @ from the end (closest to cursor) to find active mention
  for (const atIndex of atIndices) {
    const textAfterAt = textBeforeCursor.substring(atIndex + 1);
    
    // If cursor is exactly at @, this is a new mention
    if (cursorPosition === atIndex + 1) {
      return {
        atIndex,
        query: '',
        textBeforeCursor,
      };
    }
    
    // Check if this is part of a completed mention @[agentId:agentName]
    const completedMentionMatch = textAfterAt.match(/^\[[^:]+:[^\]]+\]/);
    
    if (completedMentionMatch) {
      // This is a completed mention, skip to next @
      continue;
    }

    // Check if there's already a space/newline/bracket immediately after @
    const firstChar = textAfterAt[0];
    if (firstChar === ' ' || firstChar === '\n' || firstChar === '[') {
      continue;
    }
    
    // Check if textAfterAt contains a space/newline/bracket (completed mention)
    const spaceIndex = textAfterAt.indexOf(' ');
    const newlineIndex = textAfterAt.indexOf('\n');
    const bracketIndex = textAfterAt.indexOf('[');
    
    // Find the first delimiter
    const endIndex = Math.min(
      spaceIndex === -1 ? Infinity : spaceIndex,
      newlineIndex === -1 ? Infinity : newlineIndex,
      bracketIndex === -1 ? Infinity : bracketIndex
    );
    
    // If there's a delimiter, check if cursor is past it (mention is complete)
    if (endIndex !== Infinity) {
      // Cursor position relative to this @
      const relativeCursorPos = cursorPosition - atIndex - 1;
      // If cursor is past the delimiter, mention is complete
      if (relativeCursorPos > endIndex) {
        continue;
      }
    }

    // This is an active mention - return it
    return {
      atIndex,
      query: textAfterAt,
      textBeforeCursor,
    };
  }

  // No active mention found
  return null;
}

/**
 * Calculate mention menu position relative to container element
 * Position menu above container (like Telegram), aligned to container width
 */
export function calculateMentionPosition(
  container: HTMLElement,
  menuElement?: HTMLElement | null
): { top: number; left: number; width: number; side: 'top' | 'bottom' } {
  const containerRect = container.getBoundingClientRect();
  // Use actual menu height if available, otherwise use max height
  const menuHeight = menuElement?.getBoundingClientRect().height || 192; // max-h-48 = 12rem = 192px
  const spaceAbove = containerRect.top;
  const spaceBelow = window.innerHeight - containerRect.bottom;
  
  // Prefer top, but use bottom if not enough space
  const useTop = spaceAbove >= menuHeight || spaceAbove > spaceBelow;
  
  if (useTop) {
    // Position menu directly above container - align exactly with container edges
    // Menu should "grow" from container, so we align left and width exactly
    // Bottom edge of menu should align with top edge of container (no gap)
    // For fixed positioning, getBoundingClientRect() already returns viewport coordinates
    const top = containerRect.top - menuHeight;
    const left = containerRect.left;
    const width = containerRect.width;
    return { top, left, width, side: 'top' };
  } else {
    // Position menu below container if not enough space above
    // Top edge of menu should align with bottom edge of container (no gap)
    // For fixed positioning, getBoundingClientRect() already returns viewport coordinates
    const top = containerRect.bottom;
    const left = containerRect.left;
    const width = containerRect.width;
    return { top, left, width, side: 'bottom' };
  }
}

/**
 * Insert mention into text at specified position
 * Stores @[agentId:agentName] format internally for ID preservation
 */
export function insertMention(
  text: string,
  cursorPosition: number,
  atIndex: number,
  agentId: string,
  agentName: string
): { newText: string; newCursorPosition: number } {
  // Store in format @[agentId:agentName] to preserve agent ID
  const mentionText = `@[${agentId}:${agentName}] `;
  const newText =
    text.substring(0, atIndex) + mentionText + text.substring(cursorPosition);
  const newCursorPosition = atIndex + mentionText.length;
  return { newText, newCursorPosition };
}

/**
 * Parse mentions from text
 * Returns array of { start, end, agentId, agentName } for each mention
 * Parses @[agentId:agentName] format
 */
export function parseMentions(text: string): Array<{
  start: number;
  end: number;
  agentId: string;
  agentName: string;
}> {
  const mentions: Array<{ start: number; end: number; agentId: string; agentName: string }> = [];
  // Match @[agentId:agentName] pattern
  // Use matchAll for better handling of multiple matches
  const regex = /@\[([^:]+):([^\]]+)\]/g;
  const matches = Array.from(text.matchAll(regex));

  matches.forEach((match) => {
    if (match.index !== undefined) {
      mentions.push({
        start: match.index,
        end: match.index + match[0].length,
        agentId: match[1],
        agentName: match[2],
      });
    }
  });

  return mentions;
}

/**
 * Extract plain text from text with mentions
 * Converts @[agentId:agentName] to @agentName for display/API
 */
export function extractPlainText(text: string): string {
  return text.replace(/@\[([^:]+):([^\]]+)\]/g, '@$2');
}

/**
 * Restore mention IDs for mentions without ID format
 * Finds @agentName patterns and converts them to @[agentId:agentName] if agent is found
 */
export function restoreMentionIds(
  text: string,
  agents: Array<{ id: string; name: string }>
): string {
  if (!agents || agents.length === 0) {
    return text;
  }
  
  let result = text;
  
  // Process from end to start to preserve indices
  // Find all @ symbols and check if they need ID restoration
  for (let i = text.length - 1; i >= 0; i--) {
    if (text[i] === '@') {
      const afterAt = text.substring(i + 1);
      
      // Check if this is already in @[agentId:agentName] format
      const completedMentionMatch = afterAt.match(/^\[[^:]+:[^\]]+\]/);
      if (completedMentionMatch) {
        // Skip this mention, it already has ID
        continue;
      }
      
      // Find the agent name after @ - try to match against all agent names
      // We need to find the longest matching agent name
      let bestMatch: { agent: { id: string; name: string }; name: string; length: number } | null = null;
      
      for (const agent of agents) {
        // Check if agent name matches at this position
        const agentNamePattern = agent.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`^${agentNamePattern}(?=\\s|$|\\n|@|\\[)`);
        const match = afterAt.match(regex);
        if (match && (!bestMatch || match[0].length > bestMatch.length)) {
          bestMatch = {
            agent,
            name: agent.name,
            length: match[0].length,
          };
        }
      }
      
      if (bestMatch) {
        const fullMatch = `@${bestMatch.name}`;
        const replacement = `@[${bestMatch.agent.id}:${bestMatch.agent.name}]`;
        result = result.substring(0, i) + replacement + result.substring(i + fullMatch.length);
      }
    }
  }
  
  return result;
}

/**
 * Format text for display in textarea
 * Converts @[agentId:agentName] to @agentName for better UX
 */
export function formatTextForTextarea(text: string): string {
  return text.replace(/@\[([^:]+):([^\]]+)\]/g, '@$2');
}

/**
 * Render text with mentions highlighted
 * Returns array of text parts with mentions as objects
 * Only highlights @[agentId:agentName] format mentions
 */
export function renderTextWithMentions(text: string): Array<{ text: string; isMention: boolean; agentId?: string; agentName?: string }> {
  const mentions = parseMentions(text);
  if (mentions.length === 0) {
    return [{ text, isMention: false }];
  }

  // Sort mentions by start position to ensure correct order
  const sortedMentions = [...mentions].sort((a, b) => a.start - b.start);

  const parts: Array<{ text: string; isMention: boolean; agentId?: string; agentName?: string }> = [];
  let lastIndex = 0;

  sortedMentions.forEach((mention) => {
    // Add text before mention
    if (mention.start > lastIndex) {
      const beforeText = text.substring(lastIndex, mention.start);
      if (beforeText) {
        parts.push({
          text: beforeText,
          isMention: false,
        });
      }
    }

    // Add mention - show as @agentName but keep agentId
    parts.push({
      text: `@${mention.agentName}`,
      isMention: true,
      agentId: mention.agentId,
      agentName: mention.agentName,
    });

    lastIndex = mention.end;
  });

  // Add remaining text
  if (lastIndex < text.length) {
    const remainingText = text.substring(lastIndex);
    if (remainingText) {
      parts.push({
        text: remainingText,
        isMention: false,
      });
    }
  }

  return parts;
}

/**
 * Filter agents by query string
 */
export function filterAgentsByQuery<T extends { name: string }>(
  agents: T[],
  query: string
): T[] {
  if (!query) {
    return agents;
  }
  const lowerQuery = query.toLowerCase();
  return agents.filter((agent) =>
    agent.name.toLowerCase().includes(lowerQuery)
  );
}

