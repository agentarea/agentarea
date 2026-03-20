"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { Loader2, Save, Eye, Pencil } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Streamdown } from "streamdown";
import DeleteButton from "@/components/DeleteButton";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import SkillPanel from "@/components/SkillPanel/SkillPanel";
import {
  getSkill,
  getSkillContent,
  getSkillFiles,
  getSkillFile,
  updateSkill,
  deleteSkill,
  type Skill,
  type SkillContent,
  type SkillFile,
} from "@/lib/browser-api";
import { useToast } from "@/hooks/use-toast";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  listSkillMembers,
  addSkillMember,
  removeSkillMember,
  flattenSkill,
  listSkills,
} from "@/lib/browser-api";
import { Plus, Trash2, List } from "lucide-react";
import YAML from "js-yaml";

// Parse YAML frontmatter from markdown
function parseFrontmatter(content: string): { frontmatter: Record<string, unknown>; body: string; rawFrontmatter: string } {
  let body = content;
  let rawFrontmatter = "";
  let frontmatter: Record<string, unknown> = {};

  const match = content.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/);
  if (match) {
    rawFrontmatter = match[1];
    body = match[2];
    try {
      frontmatter = YAML.load(rawFrontmatter) as Record<string, unknown> || {};
    } catch {
      frontmatter = {};
    }
  }

  return { frontmatter, body, rawFrontmatter };
}

export default function SkillDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { toast } = useToast();
  const t = useTranslations("SkillsPage");
  const tDetail = useTranslations("SkillsPage.detail");
  const skillId = params.id as string;

  const [skill, setSkill] = useState<Skill | null>(null);
  const [content, setContent] = useState<SkillContent | null>(null);
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editContent, setEditContent] = useState("");
  const [hasChanges, setHasChanges] = useState(false);

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  // Child skills state
  const [childSkills, setChildSkills] = useState<any[]>([]);
  const [allSkills, setAllSkills] = useState<any[]>([]);
  const [showAddChildDialog, setShowAddChildDialog] = useState(false);
  const [addingChildId, setAddingChildId] = useState<string>("");
  const [isAddingChild, setIsAddingChild] = useState(false);
  const [removingChildId, setRemovingChildId] = useState<string | null>(null);

  // Execution order state
  const [showExecutionOrderDialog, setShowExecutionOrderDialog] = useState(false);
  const [executionOrder, setExecutionOrder] = useState<any[]>([]);
  const [isLoadingOrder, setIsLoadingOrder] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [skillRes, contentRes, filesRes, membersRes, allSkillsRes] = await Promise.all([
          getSkill(skillId),
          getSkillContent(skillId),
          getSkillFiles(skillId),
          listSkillMembers(skillId),
          listSkills(),
        ]);

        if (skillRes.error || !skillRes.data) {
          toast({
            title: t("error.loadSkills"),
            description: t("error.skillNotFound"),
            variant: "destructive",
          });
          router.push("/skills");
          return;
        }

        const skillData = skillRes.data as Skill;
        const contentData = contentRes.data as SkillContent;
        const filesData = (filesRes.data as { files: SkillFile[] })?.files || [];

        setSkill(skillData);
        setContent(contentData);
        setFiles(filesData);
        setChildSkills((membersRes.data as any) || []);
        setAllSkills((allSkillsRes.data as any) || []);

        setEditName(skillData.name);
        setEditDescription(skillData.description || "");
        setEditContent(contentData?.content || "");

        if (contentData?.content) {
          setSelectedFile("SKILL.md");
          setFileContent(contentData.content);
        }
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [skillId, router, toast, t]);

  useEffect(() => {
    if (!skill || !content) return;

    const nameChanged = editName !== skill.name;
    const descChanged = editDescription !== (skill.description || "");
    const contentChanged =
      skill.source_type === "content" && editContent !== (content?.content || "");

    setHasChanges(nameChanged || descChanged || contentChanged);
  }, [editName, editDescription, editContent, skill, content]);

  const handleFileSelect = async (path: string) => {
    setSelectedFile(path);
    setLoadingFile(true);
    setIsEditing(false);

    try {
      if (path === "SKILL.md") {
        setFileContent(editContent || content?.content || "");
      } else {
        const { data, error } = await getSkillFile(skillId, path);
        if (error) {
          toast({
            title: t("error.loadSkills"),
            description: t("error.loadFileContent"),
            variant: "destructive",
          });
          setFileContent(null);
        } else {
          const fileData = data as { url?: string };
          if (fileData?.url) {
            const response = await fetch(fileData.url);
            const text = await response.text();
            setFileContent(text);
          } else {
            setFileContent(null);
          }
        }
      }
    } finally {
      setLoadingFile(false);
    }
  };

  const handleSave = async () => {
    if (!skill) return;

    setSaving(true);
    try {
      const updateData: any = {
        name: editName,
        description: editDescription || null,
      };

      if (skill.source_type === "content") {
        updateData.content = editContent;
      }

      const { error } = await updateSkill(skillId, updateData);

      if (error) {
        toast({
          title: t("error.loadSkills"),
          description: t("error.updateSkill"),
          variant: "destructive",
        });
        return;
      }

      const [skillRes, contentRes] = await Promise.all([
        getSkill(skillId),
        getSkillContent(skillId),
      ]);

      if (skillRes.data) {
        setSkill(skillRes.data as Skill);
      }
      if (contentRes.data) {
        setContent(contentRes.data as SkillContent);
      }

      toast({ title: t("success.skillUpdated"), description: t("success.skillUpdated") });
      setHasChanges(false);
      setIsEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleAddChildSkill = async () => {
    if (!addingChildId) return;
    setIsAddingChild(true);
    try {
      const { error } = await addSkillMember(skillId, addingChildId);
      if (error) {
        toast({ title: "Error", description: "Failed to add child skill", variant: "destructive" });
        return;
      }
      const { data } = await listSkillMembers(skillId);
      setChildSkills((data as any) || []);
      setShowAddChildDialog(false);
      setAddingChildId("");
      toast({ title: "Child skill added" });
    } finally {
      setIsAddingChild(false);
    }
  };

  const handleRemoveChildSkill = async (childId: string) => {
    setRemovingChildId(childId);
    try {
      const { error } = await removeSkillMember(skillId, childId);
      if (error) {
        toast({ title: "Error", description: "Failed to remove child skill", variant: "destructive" });
        return;
      }
      setChildSkills((prev: any[]) => prev.filter((s: any) => s.id !== childId));
      toast({ title: "Child skill removed" });
    } finally {
      setRemovingChildId(null);
    }
  };

  const handleViewExecutionOrder = async () => {
    setIsLoadingOrder(true);
    setShowExecutionOrderDialog(true);
    try {
      const { data, error } = await flattenSkill(skillId);
      if (error) {
        toast({ title: "Error", description: "Failed to fetch execution order", variant: "destructive" });
        return;
      }
      setExecutionOrder((data as any) || []);
    } finally {
      setIsLoadingOrder(false);
    }
  };

  if (loading) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("title"), href: "/skills" },
            { label: t("loading") },
          ],
        }}
      >
        <div className="flex h-64 items-center justify-center">
          <LoadingSpinner />
        </div>
      </ContentBlock>
    );
  }

  if (!skill) {
    return null;
  }

  const isContentEditable = skill.source_type === "content";
  const canEditFile = isContentEditable && selectedFile === "SKILL.md";

  // Parse frontmatter for display
  const parsed = fileContent ? parseFrontmatter(fileContent) : null;
  const hasFrontmatter = parsed && parsed.rawFrontmatter.length > 0;

  return (
    <ContentBlock
      className="p-0 overflow-hidden"
      header={{
        breadcrumb: [
          { label: t("title"), href: "/skills" },
          { label: skill.name },
        ],
        controls: (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="xs"
              onClick={handleViewExecutionOrder}
              disabled={isLoadingOrder}
            >
              <List className="mr-2 h-4 w-4" />
              View Execution Order
            </Button>
            <Button
              variant="outline"
              size="xs"
              onClick={handleSave}
              disabled={!hasChanges || saving}
            >
              {saving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              {tDetail("save")}
            </Button>
            <DeleteButton
              size="xs"
              itemId={skillId}
              itemName={skill.name}
              onDelete={deleteSkill}
              redirectPath="/skills"
              title={t("confirm.deleteSkillTitle") || tDetail("delete")}
              description={t("confirm.deleteSkill", { skillName: skill.name })}
              successMessage={t("success.skillDeleted")}
            />
          </div>
        ),
      }}
    >
      <div className="flex h-full w-full overflow-hidden">
        {/* Main Content Area */}
        <div className="flex-1 overflow-auto p-6">
          <Card className="h-full flex flex-col">
            <CardHeader className="border-b py-3 flex flex-row items-center justify-between shrink-0">
              <CardTitle className="text-sm font-mono">
                {selectedFile || tDetail("selectFile")}
              </CardTitle>
              {canEditFile && (
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => setIsEditing(!isEditing)}
                >
                  {isEditing ? (
                    <>
                      <Eye className="mr-1 h-3 w-3" /> {tDetail("view")}
                    </>
                  ) : (
                    <>
                      <Pencil className="mr-1 h-3 w-3" /> {tDetail("edit")}
                    </>
                  )}
                </Button>
              )}
            </CardHeader>
            <CardContent className="p-0 flex-1 overflow-auto relative">
              {loadingFile ? (
                <div className="absolute inset-0 flex items-center justify-center">
                  <LoadingSpinner />
                </div>
              ) : !selectedFile ? (
                <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm">
                  {tDetail("selectFile")}
                </div>
              ) : !fileContent ? (
                <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm">
                  {tDetail("emptyFile")}
                </div>
              ) : isEditing && canEditFile ? (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full h-full p-4 bg-background text-sm font-mono resize-none focus:outline-none"
                  spellCheck={false}
                />
              ) : (
                <div className="p-6 space-y-4">
                  {/* Frontmatter card */}
                  {hasFrontmatter && (
                    <div className="rounded-lg border bg-card overflow-hidden shrink-0">
                      <div className="bg-muted px-4 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b">
                        {tDetail("skillConfiguration")}
                      </div>
                      <div className="p-4">
                        <pre className="text-sm font-mono whitespace-pre-wrap text-foreground">{parsed!.rawFrontmatter}</pre>
                      </div>
                    </div>
                  )}

                  {/* Content */}
                  <div className="prose prose-sm dark:prose-invert max-w-none pb-10">
                    <Streamdown>{parsed?.body || fileContent}</Streamdown>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right Sidebar Dock */}
        <TaskInfoPanelDock
          storageKey="skill-info-panel"
          panel={
            <SkillPanel
              skill={skill}
              files={files}
              onFileSelect={handleFileSelect}
              selectedFile={selectedFile}
            />
          }
        />
      </div>

      {/* Child Skills Section */}
      <div className="border-t px-6 py-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Child Skills ({childSkills.length})</h3>
          <Button size="xs" variant="outline" onClick={() => setShowAddChildDialog(true)}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            Add Child Skill
          </Button>
        </div>
        {childSkills.length === 0 ? (
          <p className="text-sm text-muted-foreground">No child skills yet.</p>
        ) : (
          <ul className="space-y-1">
            {childSkills.map((child: any) => (
              <li key={child.id} className="flex items-center justify-between rounded border px-3 py-2 text-sm">
                <span>{child.name}</span>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() => handleRemoveChildSkill(child.id)}
                  disabled={removingChildId === child.id}
                >
                  {removingChildId === child.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  )}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Add Child Skill Dialog */}
      <Dialog open={showAddChildDialog} onOpenChange={setShowAddChildDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Child Skill</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <select
              className="w-full rounded border bg-background px-3 py-2 text-sm"
              value={addingChildId}
              onChange={(e) => setAddingChildId(e.target.value)}
            >
              <option value="">Select a skill...</option>
              {allSkills
                .filter((s: any) => s.id !== skillId && !childSkills.some((c: any) => c.id === s.id))
                .map((s: any) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
            </select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddChildDialog(false)}>Cancel</Button>
            <Button onClick={handleAddChildSkill} disabled={!addingChildId || isAddingChild}>
              {isAddingChild ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Execution Order Dialog */}
      <Dialog open={showExecutionOrderDialog} onOpenChange={setShowExecutionOrderDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Execution Order</DialogTitle>
          </DialogHeader>
          <div className="py-2">
            {isLoadingOrder ? (
              <div className="flex justify-center py-6"><LoadingSpinner /></div>
            ) : executionOrder.length === 0 ? (
              <p className="text-sm text-muted-foreground">No execution order available.</p>
            ) : (
              <ol className="space-y-1 list-decimal list-inside">
                {executionOrder.map((item: any, idx: number) => (
                  <li key={idx} className="text-sm py-1 border-b last:border-0">
                    {item.name || item.id || JSON.stringify(item)}
                  </li>
                ))}
              </ol>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowExecutionOrderDialog(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
