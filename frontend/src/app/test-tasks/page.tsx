"use client";

import TaskCreator from "@/components/TaskCreator";

export default function TestTasksPage() {
  return (
    <div className="container mx-auto py-8 px-4">
      <div className="max-w-4xl mx-auto">
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">Task Creation Testing</h1>
          <p className="text-muted-foreground">
            Use this page to test task creation functionality and verify that tasks are properly created and executed.
          </p>
        </div>
        
        <div className="flex justify-center">
          <TaskCreator />
        </div>
        
        <div className="mt-8 p-6 bg-muted/50 rounded-lg">
          <h2 className="text-lg font-semibold mb-3">How to Test:</h2>
          <ol className="list-decimal list-inside space-y-2 text-sm">
            <li>Select an agent from the dropdown (agents must be created first)</li>
            <li>Enter a task description or use one of the quick examples</li>
            <li>Click "Create Task" to send the task to the agent</li>
            <li>If successful, you'll get a task ID and links to view the task</li>
            <li>Check the task details page to see real-time execution status</li>
            <li>Visit the tasks list to see all created tasks</li>
          </ol>
          
          <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded">
            <h3 className="font-medium text-blue-900 mb-2">Useful Links:</h3>
            <ul className="text-sm text-blue-800 space-y-1">
              <li>• <a href="/agents/browse" className="underline">Browse Agents</a> - View available agents</li>
              <li>• <a href="/agents/tasks" className="underline">All Tasks</a> - View all created tasks</li>
              <li>• <a href="/chat" className="underline">Chat Interface</a> - Alternative way to send tasks</li>
              <li>• <a href="/agents/create" className="underline">Create Agent</a> - Create new agents if needed</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}