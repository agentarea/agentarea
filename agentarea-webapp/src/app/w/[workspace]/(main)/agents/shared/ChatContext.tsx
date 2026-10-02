"use client";

import React, { createContext, useContext, useState } from "react";

interface ChatContextType {
  isChatOpen: boolean;
  setIsChatOpen: (open: boolean) => void;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [isChatOpen, setIsChatOpen] = useState(false);

  return (
    <ChatContext.Provider value={{ isChatOpen, setIsChatOpen }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChat() {
  const context = useContext(ChatContext);
  // Return default values if context is not available (optional context)
  if (!context) {
    return {
      isChatOpen: false,
      setIsChatOpen: () => {},
    };
  }
  return context;
}
