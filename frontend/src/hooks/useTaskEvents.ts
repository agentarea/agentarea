import { useState, useEffect, useCallback, useRef } from "react";
import { useSSE } from "./useSSE";
import { getTaskEvents } from "./actions";
import { 
  DisplayEvent, 
  EventsState, 
  UseTaskEventsOptions,
  SSEMessage,
  TaskEventResponse,
  mapSSEToDisplayEvent,
  mapTaskEventToDisplayEvent
} from "@/types/events";

export function useTaskEvents(
  agentId: string | null, 
  taskId: string | null, 
  options: UseTaskEventsOptions = {}
) {
  const {
    includeHistory = true,
    autoConnect = true,
    filters = {},
    onEvent,
    onError,
    onConnected,
    onDisconnected
  } = options;
  
  // Store callbacks in refs to avoid dependency issues
  const onEventRef = useRef(onEvent);
  const onErrorRef = useRef(onError);
  const onConnectedRef = useRef(onConnected);
  const onDisconnectedRef = useRef(onDisconnected);
  
  // Update refs when callbacks change
  useEffect(() => {
    onEventRef.current = onEvent;
    onErrorRef.current = onError;
    onConnectedRef.current = onConnected;
    onDisconnectedRef.current = onDisconnected;
  }, [onEvent, onError, onConnected, onDisconnected]);

  const [state, setState] = useState<EventsState>({
    events: [],
    loading: false,
    error: null,
    connected: false,
    filters,
    pagination: {
      page: 1,
      pageSize: 50,
      total: 0,
      hasNext: false
    }
  });

  const eventsRef = useRef<DisplayEvent[]>([]);
  const loadedHistory = useRef(false);
  const chunkBufferRef = useRef<Map<string, DisplayEvent>>(new Map());

  // SSE URL for real-time events
  const sseUrl = agentId && taskId && autoConnect 
    ? `/api/sse/agents/${agentId}/tasks/${taskId}/events/stream`
    : null;

  // Load historical events from API
  const loadHistoricalEvents = useCallback(async () => {
    if (!agentId || !taskId || !includeHistory || loadedHistory.current) {
      return;
    }

    try {
      setState(prev => ({ ...prev, loading: true, error: null }));

      const { data, error } = await getTaskEvents(agentId, taskId, {
        page: 1,
        page_size: 100
      });
      
      if (error || !data) {
        throw new Error(error?.toString() || "Failed to load events");
      }
      
      const historicalEvents = data.events.map(mapTaskEventToDisplayEvent);
      
      eventsRef.current = historicalEvents;
      loadedHistory.current = true;
      
      setState(prev => ({
        ...prev,
        events: historicalEvents,
        loading: false,
        pagination: {
          page: data.page,
          pageSize: data.page_size,
          total: data.total,
          hasNext: data.has_next
        }
      }));

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Failed to load historical events";
      setState(prev => ({ ...prev, loading: false, error: errorMessage }));
      if (onErrorRef.current) {
        onErrorRef.current(errorMessage);
      }
    }
  }, [agentId, taskId, includeHistory]);

  // Handle SSE messages
  const handleSSEMessage = useCallback((sseEvent: { type: string; data: any }) => {
    try {
      console.log("Raw SSE event received:", sseEvent);
      
      // Handle different SSE event formats
      let parsedData: any;
      
      // Parse the data based on its type
      if (typeof sseEvent.data === 'string') {
        try {
          parsedData = JSON.parse(sseEvent.data);
        } catch (parseError) {
          console.error("Failed to parse SSE data as JSON:", sseEvent.data);
          // If JSON parsing fails, treat as raw string
          parsedData = { message: sseEvent.data };
        }
      } else if (sseEvent.data && typeof sseEvent.data === 'object') {
        parsedData = sseEvent.data;
      } else {
        console.warn("Unexpected SSE data format:", sseEvent.data);
        parsedData = { message: String(sseEvent.data) };
      }

      // Create SSE message format matching protocol structure
      // Extract rich content from original_data field (where the actual LLM response data lives)
      const originalData = parsedData.original_data || {};
      const baseData = parsedData.data || parsedData;
      
      const eventData: SSEMessage = {
        event: sseEvent.type,
        data: {
          event_type: parsedData.original_event_type || parsedData.event_type || sseEvent.type as any,
          event_id: parsedData.event_id || new Date().getTime().toString(),
          timestamp: parsedData.original_timestamp || parsedData.timestamp || new Date().toISOString(),
          data: {
            // Core fields
            task_id: baseData.task_id || parsedData.task_id || parsedData.aggregate_id || "unknown",
            agent_id: baseData.agent_id || parsedData.agent_id || "unknown",
            execution_id: baseData.execution_id || parsedData.execution_id || "unknown",
            iteration: baseData.iteration || parsedData.iteration || originalData.iteration,
            
            // Rich event content from original_data (this is where the actual LLM responses are!)
            content: originalData.content || baseData.content || parsedData.content,
            chunk: originalData.chunk || baseData.chunk || parsedData.chunk,
            chunk_index: originalData.chunk_index || baseData.chunk_index || parsedData.chunk_index,
            is_final: originalData.is_final || baseData.is_final || parsedData.is_final,
            cost: originalData.cost || baseData.cost || parsedData.cost,
            usage: originalData.usage || baseData.usage || parsedData.usage,
            tool_calls: originalData.tool_calls || baseData.tool_calls || parsedData.tool_calls,
            model_id: originalData.model_id || baseData.model_id || parsedData.model_id,
            tool_name: originalData.tool_name || baseData.tool_name || parsedData.tool_name,
            result: originalData.result || baseData.result || parsedData.result,
            success: originalData.success || baseData.success || parsedData.success,
            error: originalData.error || baseData.error || parsedData.error,
            error_type: originalData.error_type || baseData.error_type || parsedData.error_type,
            
            // Budget and goal information
            budget_remaining: originalData.budget_remaining || baseData.budget_remaining || parsedData.budget_remaining,
            total_cost: originalData.total_cost || baseData.total_cost || parsedData.total_cost,
            goal_description: originalData.goal_description || baseData.goal_description || parsedData.goal_description,
            max_iterations: originalData.max_iterations || baseData.max_iterations || parsedData.max_iterations,
            
            // Message count and other workflow data
            message_count: originalData.message_count || baseData.message_count || parsedData.message_count,
            
            // Fallback for any other data
            ...originalData,
            ...baseData
          }
        }
      };

      console.log("Processed SSE event data:", eventData);

      // Convert to display event
      const displayEvent = mapSSEToDisplayEvent(eventData);
      console.log("Display event:", displayEvent);
      
      // Regular event - add normally (avoid duplicates)
      eventsRef.current = [
        ...eventsRef.current.filter(e => e.id !== displayEvent.id),
        displayEvent
      ].sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());

      setState(prev => ({
        ...prev,
        events: eventsRef.current,
        error: null
      }));

      if (onEventRef.current) {
        onEventRef.current(displayEvent);
      }

    } catch (error) {
      console.error("Failed to process SSE event:", error, "Original event:", sseEvent);
      const errorMessage = `Failed to process real-time event: ${error instanceof Error ? error.message : String(error)}`;
      setState(prev => ({ ...prev, error: errorMessage }));
      if (onErrorRef.current) {
        onErrorRef.current(errorMessage);
      }
    }
  }, []);

  // Handle SSE connection events
  const handleSSEOpen = useCallback(() => {
    setState(prev => ({ ...prev, connected: true, error: null }));
    if (onConnectedRef.current) {
      onConnectedRef.current();
    }
  }, []);

  const handleSSEError = useCallback((error: Event) => {
    setState(prev => ({ ...prev, connected: false }));
    console.error("SSE connection error:", error);
  }, []);

  const handleSSEClose = useCallback(() => {
    setState(prev => ({ ...prev, connected: false }));
    if (onDisconnectedRef.current) {
      onDisconnectedRef.current();
    }
  }, []);

  // Initialize SSE connection
  const { isConnected, error: sseError, connect, disconnect } = useSSE(sseUrl, {
    onMessage: handleSSEMessage,
    onError: handleSSEError,
    onOpen: handleSSEOpen,
    onClose: handleSSEClose,
    reconnect: true,
    reconnectInterval: 3000
  });

  // Load historical events on mount
  useEffect(() => {
    if (agentId && taskId) {
      loadHistoricalEvents();
    }
  }, [agentId, taskId, loadHistoricalEvents]);

  // Update connection state from SSE hook
  useEffect(() => {
    setState(prev => ({ 
      ...prev, 
      connected: isConnected,
      error: sseError || prev.error
    }));
  }, [isConnected, sseError]);

  // Refresh function to reload both historical and reconnect SSE
  const refresh = useCallback(async () => {
    loadedHistory.current = false;
    eventsRef.current = [];
    chunkBufferRef.current.clear(); // Clear chunk buffer
    setState(prev => ({
      ...prev,
      events: [],
      error: null
    }));
    
    // Reload historical events manually instead of calling loadHistoricalEvents
    if (agentId && taskId && includeHistory) {
      try {
        setState(prev => ({ ...prev, loading: true, error: null }));

        const { data, error } = await getTaskEvents(agentId, taskId, {
          page: 1,
          page_size: 100
        });
        
        if (error || !data) {
          throw new Error(error?.toString() || "Failed to load events");
        }
        
        const historicalEvents = data.events.map(mapTaskEventToDisplayEvent);
        
        eventsRef.current = historicalEvents;
        loadedHistory.current = true;
        
        setState(prev => ({
          ...prev,
          events: historicalEvents,
          loading: false,
          pagination: {
            page: data.page,
            pageSize: data.page_size,
            total: data.total,
            hasNext: data.has_next
          }
        }));

      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : "Failed to load historical events";
        setState(prev => ({ ...prev, loading: false, error: errorMessage }));
        if (onErrorRef.current) {
          onErrorRef.current(errorMessage);
        }
      }
    }
    
    // Reconnect SSE
    if (sseUrl) {
      disconnect();
      setTimeout(connect, 100);
    }
  }, [agentId, taskId, includeHistory, sseUrl, connect, disconnect]);

  // Manual connect/disconnect functions
  const manualConnect = useCallback(() => {
    if (sseUrl) {
      connect();
    }
  }, [sseUrl, connect]);

  const manualDisconnect = useCallback(() => {
    disconnect();
  }, [disconnect]);

  // Clear events
  const clearEvents = useCallback(() => {
    eventsRef.current = [];
    chunkBufferRef.current.clear(); // Clear chunk buffer
    setState(prev => ({
      ...prev,
      events: [],
      error: null
    }));
  }, []);

  // Update filters
  const updateFilters = useCallback((newFilters: Partial<typeof filters>) => {
    setState(prev => ({
      ...prev,
      filters: { ...prev.filters, ...newFilters }
    }));
  }, []);

  return {
    // State
    events: state.events,
    loading: state.loading,
    error: state.error,
    connected: state.connected,
    filters: state.filters,
    pagination: state.pagination,
    
    // Actions
    refresh,
    connect: manualConnect,
    disconnect: manualDisconnect,
    clearEvents,
    updateFilters,
    
    // Utils
    hasEvents: state.events.length > 0,
    hasError: !!state.error,
    isLoading: state.loading
  };
}