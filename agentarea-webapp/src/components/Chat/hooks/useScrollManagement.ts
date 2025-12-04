/**
 * Hook for managing chat scroll behavior
 * Handles auto-scroll, bottom detection, and smooth scrolling
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface UseScrollManagementOptions {
  /**
   * Number of messages in the chat (used to trigger scroll checks)
   */
  messagesCount: number;

  /**
   * Additional dependencies to trigger scroll behavior
   */
  dependencies?: any[];
}

export interface UseScrollManagementReturn {
  /**
   * Ref for the scrollable messages container
   */
  messagesContainerRef: React.RefObject<HTMLDivElement>;

  /**
   * Ref for the element at the bottom of messages (for scrollIntoView)
   */
  messagesEndRef: React.RefObject<HTMLDivElement>;

  /**
   * Whether the user is currently scrolled to the bottom
   */
  isAtBottom: boolean;

  /**
   * Scroll event handler (attach to onScroll)
   */
  handleScroll: () => void;

  /**
   * Programmatically scroll to bottom
   */
  scrollToBottom: () => void;

  /**
   * Check if currently at bottom
   */
  checkIfAtBottom: () => boolean;
}

/**
 * Custom hook for managing scroll behavior in chat interfaces
 *
 * Features:
 * - Auto-scroll when new messages arrive (if already at bottom)
 * - Debounced scroll detection
 * - Smooth scrolling with RAF
 * - Automatic cleanup of timers/RAF
 *
 * @example
 * ```typescript
 * const {
 *   messagesContainerRef,
 *   messagesEndRef,
 *   isAtBottom,
 *   handleScroll,
 *   scrollToBottom
 * } = useScrollManagement({ messagesCount: messages.length });
 *
 * return (
 *   <div ref={messagesContainerRef} onScroll={handleScroll}>
 *     {messages.map(...)}
 *     <div ref={messagesEndRef} />
 *   </div>
 * );
 * ```
 */
export function useScrollManagement({
  messagesCount,
  dependencies = [],
}: UseScrollManagementOptions): UseScrollManagementReturn {
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const scrollRAFRef = useRef<number | null>(null);

  const [isAtBottom, setIsAtBottom] = useState(true);

  /**
   * Check if user is at the bottom of the scroll container
   * Uses a threshold to account for sub-pixel rendering
   */
  const checkIfAtBottom = useCallback(() => {
    if (!messagesContainerRef.current) return false;

    const container = messagesContainerRef.current;
    const threshold = 100; // Threshold for "close enough" to bottom
    const scrollTop = container.scrollTop;
    const clientHeight = container.clientHeight;
    const scrollHeight = container.scrollHeight;
    const isAtBottom = scrollTop + clientHeight >= scrollHeight - threshold;

    return isAtBottom;
  }, []);

  /**
   * Handle scroll events with debouncing
   * Updates isAtBottom state after a delay
   */
  const handleScroll = useCallback(() => {
    // Cancel previous timeout if it exists
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current);
    }

    // Set new timeout for debounce
    scrollTimeoutRef.current = setTimeout(() => {
      const atBottom = checkIfAtBottom();
      setIsAtBottom(atBottom);
    }, 100);
  }, [checkIfAtBottom]);

  /**
   * Programmatically scroll to bottom
   * Uses direct scrollTop manipulation for reliability
   */
  const scrollToBottom = useCallback(() => {
    if (messagesContainerRef.current) {
      messagesContainerRef.current.scrollTop =
        messagesContainerRef.current.scrollHeight;
    }
  }, []);

  /**
   * Auto-scroll to bottom when messages change (only if user was at bottom)
   * Uses RAF for smooth rendering
   */
  useEffect(() => {
    if (isAtBottom && messagesContainerRef.current) {
      // Cancel previous RAF if it exists
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }

      // Use direct scrollTop manipulation instead of scrollIntoView
      // to avoid scrolling the entire page
      scrollRAFRef.current = requestAnimationFrame(() => {
        const container = messagesContainerRef.current;
        if (container) {
          container.scrollTop = container.scrollHeight;
        }

        // Check position after scroll
        scrollRAFRef.current = requestAnimationFrame(() => {
          const atBottom = checkIfAtBottom();
          if (!atBottom && messagesContainerRef.current) {
            // Force scroll again if not at bottom
            messagesContainerRef.current.scrollTop =
              messagesContainerRef.current.scrollHeight;
          }
        });
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messagesCount, isAtBottom, checkIfAtBottom, ...dependencies]);

  /**
   * Check scroll position when container size changes
   */
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (container) {
      const checkPosition = () => {
        const atBottom = checkIfAtBottom();
        setIsAtBottom(atBottom);
      };

      scrollRAFRef.current = requestAnimationFrame(checkPosition);

      return () => {
        if (scrollRAFRef.current) {
          cancelAnimationFrame(scrollRAFRef.current);
        }
      };
    }
  }, [messagesCount, checkIfAtBottom]);

  /**
   * Cleanup timeouts and RAF on unmount
   */
  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
      if (scrollRAFRef.current) {
        cancelAnimationFrame(scrollRAFRef.current);
      }
    };
  }, []);

  return {
    messagesContainerRef,
    messagesEndRef,
    isAtBottom,
    handleScroll,
    scrollToBottom,
    checkIfAtBottom,
  };
}
