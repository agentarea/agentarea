"use client";

import React, { useEffect, useState } from "react";
import { TaskItem } from "@/components/TaskItem";
import EmptyState from "@/components/EmptyState";
import { TaskWithStatus } from "../types";

interface AgentTasksListProps {
  initialTasks: TaskWithStatus[];
}

export default function AgentTasksList({ 
  initialTasks
}: AgentTasksListProps) {
  const [tasks, setTasks] = useState<TaskWithStatus[]>(initialTasks);

  // Обновляем задачи только при изменении initialTasks
  useEffect(() => {
    setTasks(initialTasks);
  }, [initialTasks]);

  return (
    <div className="space-y-2 h-full overflow-auto px-4 py-5">
      {tasks.length === 0 ? (
        <EmptyState
          title="No tasks yet"
          description="This agent hasn't been assigned any tasks yet."
          iconsType="tasks"
          action={{
            label: "Create your first task",
            href: "./new-task"
          }}
        /> 
      ) : (
        <div className="flex flex-col gap-2">
          {tasks.map((task) => (
            <TaskItem
              key={task.id}
              task={{
                id: task.id,
                description: task.description,
                status: task.status,
                created_at: task.created_at,
                agent_id: task.agent_id,
              }}
              showAgentName={false}
            />
          ))}
        </div>
      )}
    </div>
  );
}


