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
  const lastAtIndex = textBeforeCursor.lastIndexOf('@');

  if (lastAtIndex === -1) {
    return null;
  }

  const textAfterAt = textBeforeCursor.substring(lastAtIndex + 1);
  const hasSpaceOrNewline = textAfterAt.includes(' ') || textAfterAt.includes('\n');

  if (hasSpaceOrNewline) {
    return null;
  }

  return {
    atIndex: lastAtIndex,
    query: textAfterAt,
    textBeforeCursor,
  };
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
 */
export function insertMention(
  text: string,
  cursorPosition: number,
  atIndex: number,
  agentName: string
): { newText: string; newCursorPosition: number } {
  const mentionText = `@${agentName} `;
  const newText =
    text.substring(0, atIndex) + mentionText + text.substring(cursorPosition);
  const newCursorPosition = atIndex + mentionText.length;
  return { newText, newCursorPosition };
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

