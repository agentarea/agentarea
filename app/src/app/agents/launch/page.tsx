"use client";
import React, { useState } from "react";

export default function LaunchAgentPage() {
  const [inputConfig, setInputConfig] = useState("");
  const [schedule, setSchedule] = useState("");
  const [security, setSecurity] = useState("");
  const [status, setStatus] = useState("Idle");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Add logic to launch the agent
    setStatus("Agent Launched!");
  };

  return (
    <div className="p-4">
      <h1 className="text-2xl font-bold mb-4">Launch Agent</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block font-medium">Input Parameters</label>
          <input
            type="text"
            value={inputConfig}
            onChange={(e) => setInputConfig(e.target.value)}
            placeholder="Enter input configuration"
            className="mt-1 block w-full border border-gray-300 rounded p-2"
          />
        </div>
        <div>
          <label className="block font-medium">Scheduling Options</label>
          <input
            type="text"
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
            placeholder="E.g., Cron expression or time interval"
            className="mt-1 block w-full border border-gray-300 rounded p-2"
          />
        </div>
        <div>
          <label className="block font-medium">Security Settings</label>
          <input
            type="text"
            value={security}
            onChange={(e) => setSecurity(e.target.value)}
            placeholder="Enter security options"
            className="mt-1 block w-full border border-gray-300 rounded p-2"
          />
        </div>
        <div className="flex items-center space-x-4">
          <button type="submit" className="bg-blue-600 text-white rounded px-4 py-2">Launch Agent</button>
          <span>Status: {status}</span>
        </div>
      </form>
      <div className="mt-8 p-4 border rounded bg-gray-100">
        <h2 className="text-xl font-semibold">Monitoring Dashboard</h2>
        <p>Future implementation: Display real-time metrics and logs for the agent.</p>
      </div>
    </div>
  );
} 