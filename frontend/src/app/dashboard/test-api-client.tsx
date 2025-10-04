"use client";

import { useState } from "react";
export default function TestApiClient() {
  const [testResults, setTestResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const runTests = async () => {
    setLoading(true);
    try {
      // TODO: Implement API connection tests
      setTestResults({
        message: "API connection tests not yet implemented",
        timestamp: new Date().toISOString(),
      });
    } catch (error) {
      console.error("Error running tests:", error);
      setTestResults({
        error: "Failed to run tests",
        timestamp: new Date().toISOString(),
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-8 p-6 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
        API Connection Test
      </h2>
      
      <button
        onClick={runTests}
        disabled={loading}
        className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
      >
        {loading ? "Testing..." : "Test API Connection"}
      </button>
      
      {testResults && (
        <div className="mt-4 p-4 bg-white dark:bg-gray-800 rounded-md">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">
            Test Results
          </h3>
          <pre className="text-sm text-gray-600 dark:text-gray-300 overflow-auto">
            {JSON.stringify(testResults, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
