"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Pause } from "lucide-react";

interface TimerProps {
  isTaskRunning?: boolean;
  onTimeUpdate?: (elapsedTime: number) => void;
  className?: string;
}

export default function Timer({ 
  isTaskRunning = false, 
  onTimeUpdate,
  className = "" 
}: TimerProps) {
  const [elapsedTime, setElapsedTime] = useState(0);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    setIsRunning(isTaskRunning);
  }, [isTaskRunning]);

  useEffect(() => {
    let interval: NodeJS.Timeout;

    if (isRunning) {
      interval = setInterval(() => {
        setElapsedTime((prevTime) => {
          const newTime = prevTime + 1;
          onTimeUpdate?.(newTime);
          return newTime;
        });
      }, 1000);
    }

    return () => {
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [isRunning, onTimeUpdate]);

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return (
      <span className="flex items-baseline gap-1">
        <span className="text-4xl ">{minutes.toString().padStart(2, '0')}</span>
        <span className="text-xl">:</span>
        <span className="text-xl">{remainingSeconds.toString().padStart(2, '0')}</span>
      </span>
    );
  };

  const pauseTimer = () => {
    console.log("clicked pause");
  };


  return (
    <div className={`flex flex-row gap-2 items-center ${className}`}>
      <div className="flex flex-row gap-2">
        <p className={isRunning ? "text-green-600" : ""}>
          {formatTime(elapsedTime)}
        </p>
      </div>
      {isRunning && (
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
          {/* <Button
            size="icon"
            variant="ghost"
            onClick={pauseTimer}
            className="h-6 px-2 text-xs"
          >
            <Pause className="h-3 w-3" />
          </Button> */}
        </div>
      )}
    </div>
  );
}

// Export utility functions for external use
export { Timer };
export const formatTime = (seconds: number) => {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return (
    <span className="flex items-baseline gap-1">
      <span className="text-2xl">{minutes.toString().padStart(2, '0')}</span>
      <span className="text-sm">:</span>
      <span className="text-sm">{remainingSeconds.toString().padStart(2, '0')}</span>
    </span>
  );
};
