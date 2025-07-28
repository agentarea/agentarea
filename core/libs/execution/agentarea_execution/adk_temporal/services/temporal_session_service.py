"""Temporal-based session service implementation for ADK integration."""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from ...ag.adk.sessions.base_session_service import BaseSessionService, GetSessionConfig, ListSessionsResponse
from ...ag.adk.sessions.session import Session
from ...ag.adk.sessions.state import State
from ...ag.adk.events.event import Event

logger = logging.getLogger(__name__)


class TemporalSessionService(BaseSessionService):
    """Session service that manages sessions within Temporal workflow state.
    
    This implementation keeps session data in memory during workflow execution
    and can be extended to persist to external storage if needed.
    """
    
    def __init__(self, initial_session_data: Optional[Dict[str, Any]] = None):
        """Initialize the temporal session service.
        
        Args:
            initial_session_data: Optional initial session data to load
        """
        self._sessions: Dict[str, Session] = {}
        self._app_name = "agentarea"
        
        # Load initial session if provided
        if initial_session_data:
            self._load_initial_session(initial_session_data)
    
    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        """Create a new session.
        
        Args:
            app_name: Name of the application
            user_id: User identifier
            state: Initial session state
            session_id: Optional session ID, will be generated if not provided
            
        Returns:
            Newly created Session instance
        """
        if session_id is None:
            session_id = f"session_{user_id}_{int(datetime.now().timestamp())}"
        
        # Create initial state
        initial_state = State(
            data=state or {},
            delta={}
        )
        
        # Create session
        session = Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            events=[],
            state=initial_state,
            created_time=datetime.now().timestamp()
        )
        
        # Store session
        session_key = self._get_session_key(app_name, user_id, session_id)
        self._sessions[session_key] = session
        
        logger.info(f"Created new session: {session_id} for user: {user_id}")
        return session
    
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        """Get an existing session.
        
        Args:
            app_name: Name of the application
            user_id: User identifier  
            session_id: Session identifier
            config: Optional configuration for filtering events
            
        Returns:
            Session instance if found, None otherwise
        """
        session_key = self._get_session_key(app_name, user_id, session_id)
        session = self._sessions.get(session_key)
        
        if session is None:
            logger.warning(f"Session not found: {session_id} for user: {user_id}")
            return None
        
        # Apply filtering if config is provided
        if config:
            session = self._apply_session_config(session, config)
        
        logger.debug(f"Retrieved session: {session_id} with {len(session.events)} events")
        return session
    
    async def list_sessions(
        self, *, app_name: str, user_id: str
    ) -> ListSessionsResponse:
        """List all sessions for a user.
        
        Args:
            app_name: Name of the application
            user_id: User identifier
            
        Returns:
            ListSessionsResponse containing matching sessions
        """
        matching_sessions = []
        
        for session_key, session in self._sessions.items():
            if session.app_name == app_name and session.user_id == user_id:
                # Create a copy without events/state for listing
                session_summary = Session(
                    id=session.id,
                    app_name=session.app_name,
                    user_id=session.user_id,
                    events=[],  # Empty for listing
                    state=State(data={}, delta={}),  # Empty for listing
                    created_time=session.created_time
                )
                matching_sessions.append(session_summary)
        
        logger.info(f"Found {len(matching_sessions)} sessions for user: {user_id}")
        return ListSessionsResponse(sessions=matching_sessions)
    
    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        """Delete a session.
        
        Args:
            app_name: Name of the application
            user_id: User identifier
            session_id: Session identifier
        """
        session_key = self._get_session_key(app_name, user_id, session_id)
        
        if session_key in self._sessions:
            del self._sessions[session_key]
            logger.info(f"Deleted session: {session_id} for user: {user_id}")
        else:
            logger.warning(f"Attempted to delete non-existent session: {session_id}")
    
    def _get_session_key(self, app_name: str, user_id: str, session_id: str) -> str:
        """Generate a unique key for session storage.
        
        Args:
            app_name: Name of the application
            user_id: User identifier
            session_id: Session identifier
            
        Returns:
            Unique session key
        """
        return f"{app_name}:{user_id}:{session_id}"
    
    def _apply_session_config(self, session: Session, config: GetSessionConfig) -> Session:
        """Apply filtering configuration to a session.
        
        Args:
            session: Original session
            config: Configuration for filtering
            
        Returns:
            Filtered session copy
        """
        filtered_events = list(session.events)
        
        # Filter by timestamp
        if config.after_timestamp is not None:
            filtered_events = [
                event for event in filtered_events
                if event.timestamp > config.after_timestamp
            ]
        
        # Limit number of recent events
        if config.num_recent_events is not None:
            filtered_events = filtered_events[-config.num_recent_events:]
        
        # Create filtered session copy
        filtered_session = Session(
            id=session.id,
            app_name=session.app_name,
            user_id=session.user_id,
            events=filtered_events,
            state=session.state,
            created_time=session.created_time
        )
        
        return filtered_session
    
    def _load_initial_session(self, session_data: Dict[str, Any]) -> None:
        """Load initial session data.
        
        Args:
            session_data: Session data to load
        """
        try:
            session_id = session_data.get("session_id", "default")
            user_id = session_data.get("user_id", "default")
            app_name = session_data.get("app_name", "agentarea")
            
            # Create session from data
            session = Session(
                id=session_id,
                app_name=app_name,
                user_id=user_id,
                events=[],  # Will be populated as agent runs
                state=State(
                    data=session_data.get("state", {}),
                    delta={}
                ),
                created_time=session_data.get("created_time", datetime.now().timestamp())
            )
            
            session_key = self._get_session_key(app_name, user_id, session_id)
            self._sessions[session_key] = session
            
            logger.info(f"Loaded initial session: {session_id}")
            
        except Exception as e:
            logger.error(f"Failed to load initial session data: {e}")
    
    def get_session_data(self) -> Dict[str, Any]:
        """Get current session data for Temporal workflow persistence.
        
        Returns:
            Dictionary containing session data
        """
        session_data = {}
        
        for session_key, session in self._sessions.items():
            session_data[session_key] = {
                "id": session.id,
                "app_name": session.app_name,
                "user_id": session.user_id,
                "created_time": session.created_time,
                "state": session.state.data if session.state else {},
                "event_count": len(session.events),
                # Note: We don't serialize all events here to keep size manageable
                # Events are streamed through the workflow activities
            }
        
        return session_data