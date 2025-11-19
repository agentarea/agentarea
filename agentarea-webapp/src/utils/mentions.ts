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
 * Calculate mention menu position relative to textarea
 */
export function calculateMentionPosition(
  textarea: HTMLTextAreaElement
): { top: number; left: number } {
  const textareaRect = textarea.getBoundingClientRect();
  const top = textareaRect.bottom + window.scrollY + 4;
  const left = textareaRect.left + window.scrollX;
  return { top, left };
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

