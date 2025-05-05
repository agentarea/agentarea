import React from "react";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Controller, FieldErrors, Control } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues } from "../types";

type AdvancedSettingsProps = {
  control: Control<AgentFormValues>;
  errors: FieldErrors<AgentFormValues>;
};

const AdvancedSettings = ({ control, errors }: AdvancedSettingsProps) => (
  <Card className="p-8 shadow-xl border-0 bg-white/90 hover:shadow-2xl transition-shadow">
     <h2 className="text-2xl font-bold mb-6">Advanced Settings</h2>
       <div className="flex items-center gap-2">
         <Controller
          name="planning"
          control={control}
          render={({ field }) => (
             <Checkbox
              id="planning"
              checked={!!field.value}
              onCheckedChange={field.onChange}
            />
          )}
         />
        <Label htmlFor="planning">Enable Planning</Label>
      </div>
      {getNestedErrorMessage(errors, 'planning') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'planning')}</p>}
  </Card>
);

export default AdvancedSettings; 