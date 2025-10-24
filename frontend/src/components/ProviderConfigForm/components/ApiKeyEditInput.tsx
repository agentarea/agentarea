"use client";

import { useState } from "react";
import { Edit, X } from "lucide-react";
import { FieldValues } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export default function ApiKeyEditInput({ field }: { field: FieldValues }) {
  const [editApiKey, setEditApiKey] = useState(false);

  return (
    <div className="flex items-center gap-1">
      <Input
        id="api_key"
        type="password"
        value={editApiKey ? field.value : "********"}
        onChange={field.onChange}
        placeholder="Enter your new API key"
        disabled={!editApiKey}
      />
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              type="button"
              onClick={() => {
                if (editApiKey) {
                  field.onChange("");
                  setEditApiKey(false);
                } else {
                  setEditApiKey(true);
                }
              }}
            >
              {editApiKey ? (
                <X className="h-4 w-4" />
              ) : (
                <Edit className="h-4 w-4" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {editApiKey ? "Cancel editing" : "Edit API key"}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
