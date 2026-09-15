import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

export interface ActiveTimer {
  taskId: string;
  taskTitle: string;
  projectId: string;
  projectName?: string;
  startTime: number; // timestamp in ms
}

interface TimerContextType {
  activeTimer: ActiveTimer | null;
  elapsedSeconds: number;
  startTimer: (task: { id: string; title: string; projectId: string; projectName?: string }) => void;
  stopTimer: () => ActiveTimer | null;
  clearTimer: () => void;
  formatTime: (seconds: number) => string;
}

const TimerContext = createContext<TimerContextType | null>(null);

const STORAGE_KEY = "ems_active_timer_v1";

export function TimerProvider({ children }: { children: ReactNode }) {
  const [activeTimer, setActiveTimer] = useState<ActiveTimer | null>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved);
    } catch {
      // ignore
    }
    return null;
  });

  const [elapsedSeconds, setElapsedSeconds] = useState<number>(() => {
    if (activeTimer) {
      return Math.floor((Date.now() - activeTimer.startTime) / 1000);
    }
    return 0;
  });

  useEffect(() => {
    if (!activeTimer) {
      setElapsedSeconds(0);
      return;
    }
    // Update initial diff
    setElapsedSeconds(Math.max(0, Math.floor((Date.now() - activeTimer.startTime) / 1000)));

    const interval = setInterval(() => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - activeTimer.startTime) / 1000)));
    }, 1000);

    return () => clearInterval(interval);
  }, [activeTimer]);

  function startTimer(task: { id: string; title: string; projectId: string; projectName?: string }) {
    const timer: ActiveTimer = {
      taskId: task.id,
      taskTitle: task.title,
      projectId: task.projectId,
      projectName: task.projectName,
      startTime: Date.now(),
    };
    setActiveTimer(timer);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(timer));
    } catch {
      // ignore
    }
  }

  function stopTimer(): ActiveTimer | null {
    const current = activeTimer;
    setActiveTimer(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    return current;
  }

  function clearTimer() {
    setActiveTimer(null);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }

  function formatTime(totalSeconds: number): string {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const pad = (n: number) => n.toString().padStart(2, "0");
    if (h > 0) {
      return `${pad(h)}:${pad(m)}:${pad(s)}`;
    }
    return `${pad(m)}:${pad(s)}`;
  }

  return (
    <TimerContext.Provider
      value={{
        activeTimer,
        elapsedSeconds,
        startTimer,
        stopTimer,
        clearTimer,
        formatTime,
      }}
    >
      {children}
    </TimerContext.Provider>
  );
}

export function useTimer() {
  const context = useContext(TimerContext);
  if (!context) {
    throw new Error("useTimer must be used within a TimerProvider");
  }
  return context;
}
