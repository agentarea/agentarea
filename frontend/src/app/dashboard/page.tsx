import TestApiClient from "./test-api-client";

export default function DashboardPage() {
  // Authentication is handled by middleware and AuthGuard in ConditionalLayout

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-lg p-6">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
            Dashboard
          </h1>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            Welcome to your AgentArea dashboard!
          </p>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-6">
              <h2 className="text-xl font-semibold text-blue-800 dark:text-blue-200 mb-2">
                Agents
              </h2>
              <p className="text-blue-600 dark:text-blue-300">
                Manage your AI agents
              </p>
            </div>
            
            <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-6">
              <h2 className="text-xl font-semibold text-green-800 dark:text-green-200 mb-2">
                Tasks
              </h2>
              <p className="text-green-600 dark:text-green-300">
                View and assign tasks
              </p>
            </div>
            
            <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-6">
              <h2 className="text-xl font-semibold text-purple-800 dark:text-purple-200 mb-2">
                Connections
              </h2>
              <p className="text-purple-600 dark:text-purple-300">
                Manage MCP connections
              </p>
            </div>
          </div>
          
          <div className="mt-8">
            <h2 className="text-2xl font-semibold text-gray-900 dark:text-white mb-4">
              Recent Activity
            </h2>
            <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
              <p className="text-gray-600 dark:text-gray-400">
                No recent activity to display.
              </p>
            </div>
          </div>
          
          <TestApiClient />
        </div>
      </div>
    </div>
  );
}
