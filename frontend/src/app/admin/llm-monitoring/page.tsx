"use client";

import React, { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle,
  RefreshCw,
  Clock,
  XCircle,
  CheckCircle,
  TrendingUp,
  AlertCircle,
} from "lucide-react";

interface ErrorSummary {
  status?: string;
  error?: string;
  auth_failures: Record<string, number>;
  total_auth_failures: number;
}

interface AuthFailure {
  timestamp: string;
  error: string;
  iteration: number;
  task_id: string;
}

interface AuthFailures {
  status?: string;
  error?: string;
  failures: Record<string, AuthFailure[]>;
}

export default function LLMMonitoringPage() {
  const [errorSummary, setErrorSummary] = useState<ErrorSummary | null>(null);
  const [authFailures, setAuthFailures] = useState<AuthFailures | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      // Fetch error summary
      const summaryResponse = await fetch("/api/v1/llm-errors/summary");
      const summaryData = await summaryResponse.json();
      setErrorSummary(summaryData);

      // Fetch detailed auth failures
      const failuresResponse = await fetch("/api/v1/llm-errors/auth-failures");
      const failuresData = await failuresResponse.json();
      setAuthFailures(failuresData);

      setLastRefresh(new Date());
    } catch (error) {
      console.error("Failed to fetch LLM monitoring data:", error);
      setErrorSummary({
        error: "Failed to fetch data",
        auth_failures: {},
        total_auth_failures: 0,
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (count: number) => {
    if (count === 0) return "text-green-600 bg-green-50 border-green-200";
    if (count < 5) return "text-yellow-600 bg-yellow-50 border-yellow-200";
    return "text-red-600 bg-red-50 border-red-200";
  };

  const getStatusIcon = (count: number) => {
    if (count === 0) return <CheckCircle className="h-4 w-4" />;
    if (count < 5) return <AlertTriangle className="h-4 w-4" />;
    return <XCircle className="h-4 w-4" />;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">LLM Monitoring</h1>
          <p className="text-gray-600 mt-2">
            Monitor LLM authentication errors and performance issues
          </p>
        </div>
        <div className="flex items-center gap-4">
          {lastRefresh && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Clock className="h-4 w-4" />
              Last updated: {lastRefresh.toLocaleTimeString()}
            </div>
          )}
          <Button
            onClick={fetchData}
            disabled={loading}
            variant="outline"
            className="gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-lg">
              <AlertCircle className="h-5 w-5 text-red-500" />
              Total Auth Failures
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-red-600">
              {errorSummary?.total_auth_failures || 0}
            </div>
            <p className="text-sm text-gray-500 mt-1">Across all models</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-lg">
              <TrendingUp className="h-5 w-5 text-blue-500" />
              Affected Models
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-blue-600">
              {errorSummary
                ? Object.keys(errorSummary.auth_failures).length
                : 0}
            </div>
            <p className="text-sm text-gray-500 mt-1">Models with failures</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-lg">
              <CheckCircle className="h-5 w-5 text-green-500" />
              System Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div
              className={`text-3xl font-bold ${
                (errorSummary?.total_auth_failures || 0) === 0
                  ? "text-green-600"
                  : "text-red-600"
              }`}
            >
              {(errorSummary?.total_auth_failures || 0) === 0
                ? "Healthy"
                : "Issues"}
            </div>
            <p className="text-sm text-gray-500 mt-1">Overall health</p>
          </CardContent>
        </Card>
      </div>

      {/* Error Details */}
      {errorSummary?.error && (
        <Card className="border-red-200 bg-red-50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-red-700">
              <XCircle className="h-5 w-5" />
              Error Loading Data
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-red-600">{errorSummary.error}</p>
          </CardContent>
        </Card>
      )}

      {/* Model-specific Auth Failures */}
      {errorSummary && !errorSummary.error && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-yellow-500" />
              Authentication Failures by Model
            </CardTitle>
          </CardHeader>
          <CardContent>
            {Object.keys(errorSummary.auth_failures).length === 0 ? (
              <div className="text-center py-8">
                <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 mb-2">
                  No Authentication Failures
                </h3>
                <p className="text-gray-500">
                  All models are authenticating successfully.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {Object.entries(errorSummary.auth_failures).map(
                  ([modelId, count]) => (
                    <div
                      key={modelId}
                      className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
                    >
                      <div className="flex items-center gap-3">
                        <div className="font-mono text-sm bg-white px-2 py-1 rounded border">
                          {modelId}
                        </div>
                      </div>
                      <Badge
                        variant="secondary"
                        className={`gap-1 ${getStatusColor(count)}`}
                      >
                        {getStatusIcon(count)}
                        {count} failures
                      </Badge>
                    </div>
                  )
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Recent Failures */}
      {authFailures &&
        !authFailures.error &&
        Object.keys(authFailures.failures).length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="h-5 w-5 text-blue-500" />
                Recent Authentication Failures
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {Object.entries(authFailures.failures).map(
                  ([modelId, failures]) => (
                    <div key={modelId} className="border rounded-lg p-4">
                      <h4 className="font-medium text-gray-900 mb-3">
                        Model: {modelId}
                      </h4>
                      <div className="space-y-2">
                        {failures.slice(-3).map((failure, index) => (
                          <div
                            key={index}
                            className="flex items-start gap-3 text-sm bg-red-50 p-3 rounded"
                          >
                            <XCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
                            <div className="flex-1">
                              <p className="text-red-700 font-medium">
                                {failure.error}
                              </p>
                              <div className="flex items-center gap-4 mt-1 text-red-600">
                                <span>
                                  Task: {failure.task_id.slice(0, 8)}...
                                </span>
                                <span>Iteration: {failure.iteration}</span>
                                <span>
                                  {new Date(failure.timestamp).toLocaleString()}
                                </span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                )}
              </div>
            </CardContent>
          </Card>
        )}

      {/* Loading State */}
      {loading && !errorSummary && (
        <Card>
          <CardContent className="flex items-center justify-center py-12">
            <div className="flex items-center gap-3">
              <RefreshCw className="h-6 w-6 animate-spin text-blue-500" />
              <span className="text-gray-600">Loading monitoring data...</span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
