import React from "react";
import { Card } from "@/components/ui/card";
import { Info as InfoIcon } from "lucide-react";

const InstructionInfo = () => (
  <Card className="p-6 bg-blue-50 border-blue-200 shadow-md flex flex-col gap-2">
    <div className="flex items-center gap-2 mb-2">
      <InfoIcon className="h-5 w-5 text-blue-500" />
      <span className="font-semibold text-blue-900">About the Instruction Parameter</span>
    </div>
    <div className="text-sm text-blue-900">
      <p className="mb-2">
        <b>Instruction</b> is the most important setting for shaping your agent&apos;s behavior. It defines:
      </p>
      <ul className="list-disc pl-5 mb-2">
        <li>Core task or goal</li>
        <li>Personality or persona</li>
        <li>Constraints (e.g., allowed topics, forbidden info)</li>
        <li>How and when to use tools</li>
        <li>Desired output format</li>
      </ul>
      <b>Tips:</b>
      <ul className="list-disc pl-5">
        <li>Be clear and specific</li>
        <li>Use markdown for structure</li>
        <li>Provide examples for complex tasks</li>
        <li>Guide tool use, not just list tools</li>
      </ul>
    </div>
  </Card>
);

export default InstructionInfo; 