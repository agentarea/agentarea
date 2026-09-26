"use client";

import React, { createContext, useContext, useState } from "react";

interface ChatContextType {
  isChatSheetOpen: boolean;
  setIsChatSheetOpen: (open: boolean) => void;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [isChatSheetOpen, setIsChatSheetOpen] = useState(false);

  return (
    <ChatContext.Provider value={{ isChatSheetOpen, setIsChatSheetOpen }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChat() {
  const context = useContext(ChatContext);
  // Return default values if context is not available (optional context)
  if (!context) {
    return {
      isChatSheetOpen: false,
      setIsChatSheetOpen: () => {},
    };
  }
  return context;
}

