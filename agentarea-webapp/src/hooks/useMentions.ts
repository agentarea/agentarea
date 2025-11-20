import { useState, useEffect, useRef, useCallback } from 'react';
import { listAgents } from '@/lib/browser-api';
import {
  findMentionPosition,
  calculateMentionPosition,
  insertMention,
  filterAgentsByQuery,
} from '@/utils/mentions';

export interface Agent {
  id: string;
  name: string;
  avatar?: string;
}

interface UseMentionsOptions {
  textareaRef: React.RefObject<HTMLTextAreaElement | null> | React.RefObject<HTMLTextAreaElement> | React.RefObject<{ selectionStart: number; value?: string } | null>;
  containerRef?: React.RefObject<HTMLDivElement | null> | React.RefObject<HTMLDivElement>;
  onMentionInsert?: (text: string, cursorPosition: number) => void;
}

interface UseMentionsReturn {
  showMentions: boolean;
  mentionQuery: string;
  mentionPosition: { top: number; left: number; width: number; side: 'top' | 'bottom' };
  filteredAgents: Agent[];
  selectedMentionIndex: number;
  mentionMenuRef: React.RefObject<HTMLDivElement | null>;
  agents: Agent[];
  handleInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  handleAgentSelect: (agent: Agent) => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => boolean;
  setShowMentions: (show: boolean) => void;
}

export function useMentions({
  textareaRef,
  containerRef,
  onMentionInsert,
}: UseMentionsOptions): UseMentionsReturn {
  const [showMentions, setShowMentions] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionPosition, setMentionPosition] = useState<{ top: number; left: number; width: number; side: 'top' | 'bottom' }>({ top: 0, left: 0, width: 0, side: 'top' });
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedMentionIndex, setSelectedMentionIndex] = useState(0);
  const mentionMenuRef = useRef<HTMLDivElement | null>(null);

  // Fetch agents
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const { data, error } = await listAgents();

        if (error) {
          console.error('Failed to fetch agents:', error);
          setAgents([]);
          return;
        }

        if (data && Array.isArray(data)) {
          const formattedAgents: Agent[] = data.map((agent: any) => ({
            id: agent.id,
            name: agent.name,
            avatar: agent.avatar || undefined,
          }));
          setAgents(formattedAgents);
        } else {
          console.warn('Unexpected agents API response format:', data);
          setAgents([]);
        }
      } catch (error) {
        console.error('Failed to fetch agents:', error);
        setAgents([]);
      }
    };
    fetchAgents();
  }, []);

  // Filter agents based on query
  const filteredAgents = filterAgentsByQuery(agents, mentionQuery);

  // Reset selected index when filtered agents change - start with no selection
  useEffect(() => {
    setSelectedMentionIndex(-1);
  }, [filteredAgents.length, mentionQuery]);

  // Recalculate position when menu content changes or menu is shown
  useEffect(() => {
    if (showMentions && filteredAgents.length > 0) {
      const updatePosition = () => {
        const container = containerRef?.current || textareaRef.current;
        if (container && 'getBoundingClientRect' in container) {
          const position = calculateMentionPosition(container as HTMLElement, mentionMenuRef.current);
          setMentionPosition(position);
        }
      };
      
      // Use double requestAnimationFrame to ensure DOM is fully updated
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          updatePosition();
        });
      });
    }
  }, [showMentions, filteredAgents.length, mentionQuery, containerRef, textareaRef]);

  // Handle input change with mention detection
  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const value = e.target.value;
      const cursorPosition = e.target.selectionStart || value.length;
      const mentionPos = findMentionPosition(value, cursorPosition);

      if (mentionPos) {
        setMentionQuery(mentionPos.query);
        setShowMentions(true);
        setTimeout(() => {
          const container = containerRef?.current || textareaRef.current;
          if (container && 'getBoundingClientRect' in container) {
            const position = calculateMentionPosition(container as HTMLElement, mentionMenuRef.current);
            setMentionPosition(position);
          }
        }, 0);
      } else {
        setShowMentions(false);
      }
    },
    [textareaRef, containerRef]
  );

  // Handle agent selection
  const handleAgentSelect = useCallback(
    (selectedAgent: Agent) => {
      if (!textareaRef.current) return;

      const textarea = textareaRef.current;
      const value = (textarea as HTMLTextAreaElement).value || '';
      const cursorPosition = textarea.selectionStart;
      const mentionPos = findMentionPosition(value, cursorPosition);

      if (mentionPos) {
        const { newText, newCursorPosition } = insertMention(
          value,
          cursorPosition,
          mentionPos.atIndex,
          selectedAgent.id,
          selectedAgent.name
        );

        setShowMentions(false);
        onMentionInsert?.(newText, newCursorPosition);

        setTimeout(() => {
          if (textareaRef.current) {
            // Handle both HTMLTextAreaElement and MentionTextareaHandle
            if ('setSelectionRange' in textareaRef.current) {
              (textareaRef.current as HTMLTextAreaElement).setSelectionRange(
                newCursorPosition,
                newCursorPosition
              );
              (textareaRef.current as HTMLTextAreaElement).focus();
            } else if ('setSelectionRange' in textareaRef.current) {
              (textareaRef.current as any).setSelectionRange(
                newCursorPosition,
                newCursorPosition
              );
              (textareaRef.current as any).focus();
            }
          }
        }, 0);
      }
    },
    [textareaRef, onMentionInsert]
  );

  // Handle keyboard navigation in mention menu
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>): boolean => {
      if (!showMentions || filteredAgents.length === 0) {
        return false;
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedMentionIndex((prev) => {
          if (prev === -1) return 0;
          return prev < filteredAgents.length - 1 ? prev + 1 : 0;
        });
        return true;
      }

      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedMentionIndex((prev) => {
          if (prev === -1) return filteredAgents.length - 1;
          return prev > 0 ? prev - 1 : filteredAgents.length - 1;
        });
        return true;
      }

      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (selectedMentionIndex >= 0 && selectedMentionIndex < filteredAgents.length) {
          handleAgentSelect(filteredAgents[selectedMentionIndex]);
        }
        return true;
      }

      if (e.key === 'Escape') {
        e.preventDefault();
        setShowMentions(false);
        return true;
      }

      return false;
    },
    [showMentions, filteredAgents, selectedMentionIndex, handleAgentSelect]
  );

  // Close mention menu when clicking outside
  useEffect(() => {
      const handleClickOutside = (event: MouseEvent) => {
        const target = event.target as Node;
        const textarea = textareaRef.current;
        const isTextareaElement = textarea && 'contains' in textarea;
        
        if (
          mentionMenuRef.current &&
          !mentionMenuRef.current.contains(target) &&
          (!isTextareaElement || !textarea.contains(target))
        ) {
          setShowMentions(false);
        }
      };

    if (showMentions) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [showMentions, textareaRef]);

  return {
    showMentions,
    mentionQuery,
    mentionPosition,
    filteredAgents,
    selectedMentionIndex,
    mentionMenuRef,
    agents, // Export agents list
    handleInputChange,
    handleAgentSelect,
    handleKeyDown,
    setShowMentions,
  };
}

