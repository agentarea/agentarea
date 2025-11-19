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
  textareaRef: React.RefObject<HTMLTextAreaElement | null> | React.RefObject<HTMLTextAreaElement>;
  onMentionInsert?: (text: string, cursorPosition: number) => void;
}

interface UseMentionsReturn {
  showMentions: boolean;
  mentionQuery: string;
  mentionPosition: { top: number; left: number };
  filteredAgents: Agent[];
  selectedMentionIndex: number;
  mentionMenuRef: React.RefObject<HTMLDivElement>;
  handleInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  handleAgentSelect: (agent: Agent) => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => boolean;
  setShowMentions: (show: boolean) => void;
}

export function useMentions({
  textareaRef,
  onMentionInsert,
}: UseMentionsOptions): UseMentionsReturn {
  const [showMentions, setShowMentions] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionPosition, setMentionPosition] = useState({ top: 0, left: 0 });
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedMentionIndex, setSelectedMentionIndex] = useState(0);
  const mentionMenuRef = useRef<HTMLDivElement>(null);

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

  // Reset selected index when filtered agents change
  useEffect(() => {
    if (filteredAgents.length > 0) {
      setSelectedMentionIndex(0);
    }
  }, [filteredAgents.length, mentionQuery]);

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
          if (textareaRef.current) {
            const position = calculateMentionPosition(textareaRef.current);
            setMentionPosition(position);
          }
        }, 0);
      } else {
        setShowMentions(false);
      }
    },
    [textareaRef]
  );

  // Handle agent selection
  const handleAgentSelect = useCallback(
    (selectedAgent: Agent) => {
      if (!textareaRef.current) return;

      const textarea = textareaRef.current;
      const value = textarea.value;
      const cursorPosition = textarea.selectionStart;
      const mentionPos = findMentionPosition(value, cursorPosition);

      if (mentionPos) {
        const { newText, newCursorPosition } = insertMention(
          value,
          cursorPosition,
          mentionPos.atIndex,
          selectedAgent.name
        );

        setShowMentions(false);
        onMentionInsert?.(newText, newCursorPosition);

        setTimeout(() => {
          if (textareaRef.current) {
            textareaRef.current.setSelectionRange(
              newCursorPosition,
              newCursorPosition
            );
            textareaRef.current.focus();
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
        setSelectedMentionIndex((prev) =>
          prev < filteredAgents.length - 1 ? prev + 1 : 0
        );
        return true;
      }

      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedMentionIndex((prev) =>
          prev > 0 ? prev - 1 : filteredAgents.length - 1
        );
        return true;
      }

      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleAgentSelect(filteredAgents[selectedMentionIndex]);
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
      if (
        mentionMenuRef.current &&
        !mentionMenuRef.current.contains(event.target as Node) &&
        textareaRef.current &&
        !textareaRef.current.contains(event.target as Node)
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
    handleInputChange,
    handleAgentSelect,
    handleKeyDown,
    setShowMentions,
  };
}

