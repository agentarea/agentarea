import React from "react";

export default function AddNewAgentPage() {
  return (
    <div className="p-4">
      <h1 className="text-2xl font-bold">Add New Agent</h1>
      <form className="mt-4 space-y-4">
        <div>
          <label className="block font-medium">Agent Name</label>
          <input
            type="text"
            placeholder="Enter agent name"
            className="mt-1 block w-full border border-gray-300 rounded p-2"
          />
        </div>
        <div>
          <label className="block font-medium">Description</label>
          <textarea
            placeholder="Enter agent description"
            className="mt-1 block w-full border border-gray-300 rounded p-2"
            rows={3}
          ></textarea>
        </div>
        <div>
          <label className="block font-medium">Input/Output Specifications</label>
          <textarea
            placeholder="Enter I/O specifications"
            className="mt-1 block w-full border border-gray-300 rounded p-2"
            rows={3}
          ></textarea>
        </div>
        <div>
          <label className="block font-medium">Tags</label>
          <input
            type="text"
            placeholder="Enter tags separated by commas"
            className="mt-1 block w-full border border-gray-300 rounded p-2"
          />
        </div>
        <div>
          <label className="block font-medium">Integration Options</label>
          <input
            type="text"
            placeholder="E.g., Slack, Google Sheets"
            className="mt-1 block w-full border border-gray-300 rounded p-2"
          />
        </div>
        <div>
          <label className="block font-medium">Upload Code / YAML / JSON</label>
          <input type="file" className="mt-1 block" />
        </div>
        <div>
          <button type="submit" className="bg-blue-600 text-white rounded px-4 py-2">
            Test Agent
          </button>
        </div>
      </form>
    </div>
  );
} 