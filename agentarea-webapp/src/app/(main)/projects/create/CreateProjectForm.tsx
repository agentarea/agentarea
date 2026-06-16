"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Sparkles, BookOpen } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import FormLabel from "@/components/FormLabel/FormLabel";
import { createProjectAction } from "@/lib/server-actions";
import { useToast } from "@/hooks/use-toast";

export function CreateProjectForm() {
  const { toast } = useToast();
  const router = useRouter();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();

    if (!name.trim()) {
      toast({
        title: "Validation Error",
        description: "Project name is required",
        variant: "destructive",
      });
      return;
    }

    try {
      const { data, error } = await createProjectAction({
        name: name.trim(),
        description: description.trim() || null,
        instructions: instructions.trim() || null,
      });

      if (error) {
        toast({
          title: "Failed to create project",
          description: (error as any)?.detail || "Failed to create project",
          variant: "destructive",
        });
        return;
      }

      toast({
        title: "Project created",
        variant: "success",
      });

      const projectId = (data as any)?.id;
      router.push(projectId ? `/projects/${projectId}` : "/projects");
    } catch {
      toast({
        title: "Failed to create project",
        description: "An unexpected error occurred",
        variant: "destructive",
      });
    }
  };

  return (
    <form id="create-project-form" onSubmit={handleSubmit} className="overflow-auto h-full">
      <div className="form-content lg:max-w-xl lg:mx-auto space-y-4">
        <div className="grid gap-2">
          <FormLabel htmlFor="project-name" icon={Sparkles} required>
            Name
          </FormLabel>
          <Input
            id="project-name"
            placeholder="My project"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="project-description" icon={FileText} required={false}>
            Description
          </FormLabel>
          <Textarea
            id="project-description"
            placeholder="Brief description of this project"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="project-instructions" icon={BookOpen} required={false}>
            Instructions
          </FormLabel>
          <Textarea
            id="project-instructions"
            placeholder="Instructions for agents working within this project"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            rows={5}
          />
        </div>
      </div>
    </form>
  );
}
