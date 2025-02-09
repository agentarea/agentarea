"use client";

import React, { useState } from "react";

export default function ChatInterfacePage() {
  const [messages, setMessages] = useState<string[]>([]);
  const [input, setInput] = useState("");

  const handleSend = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() === "") return;
    setMessages([...messages, input]);
    setInput("");
  };

  return (
    <div className="p-4 flex flex-col h-full">
      <h1 className="text-2xl font-bold mb-4">Chat Interface</h1>
      <div className="flex-1 border rounded p-4 mb-4 overflow-y-auto">
        {messages.length === 0 ? (
          <p className="text-gray-500">No messages yet. Start the conversation!</p>
        ) : (
          messages.map((msg, idx) => (
            <div key={idx} className="mb-2 p-2 bg-gray-100 rounded">
              {msg}
            </div>
          ))
        )}
      </div>
      <form onSubmit={handleSend} className="flex">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message..."
          className="flex-1 border rounded-l p-2"
        />
        <button type="submit" className="bg-blue-600 text-white px-4 rounded-r">
          Send
        </button>
      </form>
    </div>
  );
} 