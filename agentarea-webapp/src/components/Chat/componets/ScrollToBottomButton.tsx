"use client";

import React from "react";
import { Button } from "@/components/ui/button";
import { ChevronDown } from "lucide-react";

interface ScrollToBottomButtonProps {
  visible: boolean;
  onScrollToBottom: () => void;
}

export const ScrollToBottomButton: React.FC<ScrollToBottomButtonProps> = ({
  visible,
  onScrollToBottom,
}) => {
  return (
    <div
      className={`absolute bottom-4 right-4 z-20 transition-opacity duration-200 ${
        visible ? "opacity-100" : "pointer-events-none opacity-0"
      }`}
    >
      <Button
        onClick={onScrollToBottom}
        size="icon"
        variant="outline"
        className="h-8 w-8 rounded-full shadow-lg"
      >
        <ChevronDown className="h-4 w-4" />
      </Button>
    </div>
  );
};

