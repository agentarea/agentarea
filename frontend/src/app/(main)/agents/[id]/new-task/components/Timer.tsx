"use client";

import { useEffect, useRef, useState } from "react";

interface TimerProps {
  isTaskRunning?: boolean;
  onTimeUpdate?: (elapsedTime: number) => void;
  className?: string;
}

export default function Timer({
  isTaskRunning = false,
  onTimeUpdate,
  className = "",
}: TimerProps) {
  const [elapsedTime, setElapsedTime] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setIsRunning(isTaskRunning);
  }, [isTaskRunning]);

  useEffect(() => {
    if (!isRunning) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    intervalRef.current = setInterval(() => {
      setElapsedTime((prevTime) => {
        const newTime = prevTime + 1;
        onTimeUpdate?.(newTime);
        return newTime;
      });
    }, 1000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isRunning, onTimeUpdate]);

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return (
      <span className="flex items-baseline gap-1">
        <span className="text-xl">{minutes.toString().padStart(2, "0")}</span>
        <span className="text-sm">:</span>
        <span className="text-sm">
          {remainingSeconds.toString().padStart(2, "0")}
        </span>
      </span>
    );
  };

  return (
    <div
      className={`flex flex-row items-center gap-2 ${className}`}
      aria-live="polite"
    >
      <p className={isRunning ? "text-green-600" : ""}>
        {formatTime(elapsedTime)}
      </p>
      {isRunning && (
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 animate-pulse rounded-full bg-green-500"></div>
        </div>
      )}
    </div>
  );
}
