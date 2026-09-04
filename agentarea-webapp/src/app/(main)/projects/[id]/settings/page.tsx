"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import FormLabel from "@/components/FormLabel/FormLabel";
import { FormSkeleton } from "@/components/Skeleton";
import { useToast } from "@/hooks/use-toast";
import { getProjectAction, updateProjectAction } from "@/lib/server-actions";
import type { ProjectResponse } from "@/api/client/types.gen";

export default function ProjectSettingsPage() {
  const params = useParams();
  const projectId = params.id as string;
  const { toast } = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const { data } = await getProjectAction(projectId);
        if (data) {
          const project = data as ProjectResponse;
          setName(project.name || "");
          setDescription(project.description || "");
          setInstructions(project.instructions || "");
        }
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [projectId]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      toast({ title: "Validation Error", description: "Project name is required", variant: "destructive" });
      return;
    }

    setSaving(true);
    try {
      const { error } = await updateProjectAction(projectId, {
        name: name.trim(),
        description: description.trim() || null,
        instructions: instructions.trim() || null,
      });

      if (error) {
        toast({
          title: "Failed to save",
          description: (error as { detail?: string })?.detail || "Failed to save project",
          variant: "destructive",
        });
        return;
      }

      toast({ title: "Project saved", variant: "success" });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <FormSkeleton className="p-6 lg:max-w-xl" fields={3} />;
  }

  return (
    <div className="p-6">
      <form id="project-settings-form" onSubmit={handleSave} className="space-y-4 lg:max-w-xl">
        <div className="grid gap-2">
          <FormLabel htmlFor="settings-name" required>
            Name
          </FormLabel>
          <Input
            id="settings-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="settings-description" required={false}>
            Description
          </FormLabel>
          <Textarea
            id="settings-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="settings-instructions" required={false}>
            Instructions
          </FormLabel>
          <Textarea
            id="settings-instructions"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            rows={5}
          />
        </div>
        <div className="flex justify-end">
          <Button type="submit" size="xs" disabled={saving}>
            {saving ? <Loader2 className="mr-2 animate-spin" /> : null}
            Save Changes
          </Button>
        </div>
      </form>
    </div>
  );
}
