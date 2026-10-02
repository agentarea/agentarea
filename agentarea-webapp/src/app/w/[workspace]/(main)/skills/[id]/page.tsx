"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import YAML from "js-yaml";
import {
  Eye,
  FileText,
  FileX,
  Loader2,
  Pencil,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { Streamdown } from "streamdown";
import ContentBlock from "@/components/ContentBlock";
import DeleteButton from "@/components/DeleteButton";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { DetailSkeleton } from "@/components/Skeleton";
import SkillPanel from "@/components/SkillPanel/SkillPanel";
import Section from "@/components/TaskInfoPanel/components/Section";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import FormError from "@/components/FormError";
import type {
  Skill,
  SkillContent,
  SkillFile,
  SkillUpdateRequest,
} from "@/lib/api";
import { apiErrorMessage, formatApiError, isApiNotFound } from "@/lib/api-errors";
import {
  addSkillMemberAction as addSkillMember,
  deleteSkillAction as deleteSkill,
  getSkillAction as getSkill,
  getSkillContentAction as getSkillContent,
  getSkillFileAction as getSkillFile,
  installSkillAction as installSkill,
  listSkillMembersAction as listSkillMembers,
  loadSkillDetailAction,
  removeSkillMemberAction as removeSkillMember,
  updateSkillAction as updateSkill,
} from "@/lib/server-actions";

// Parse YAML frontmatter from markdown
function parseFrontmatter(content: string): {
  frontmatter: Record<string, unknown>;
  body: string;
  rawFrontmatter: string;
} {
  let body = content;
  let rawFrontmatter = "";
  let frontmatter: Record<string, unknown> = {};

  const match = content.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/);
  if (match) {
    rawFrontmatter = match[1];
    body = match[2];
    try {
      frontmatter =
        (YAML.load(rawFrontmatter) as Record<string, unknown>) || {};
    } catch {
      frontmatter = {};
    }
  }

  return { frontmatter, body, rawFrontmatter };
}

export default function SkillDetailPage() {
  const params = useParams();
  const router = useWorkspaceRouter();
  const t = useTranslations("SkillsPage");
  const tDetail = useTranslations("SkillsPage.detail");
  const tChildren = useTranslations("SkillsPage.children");
  const tCommon = useTranslations("Common");
  const skillId = params.id as string;

  const [skill, setSkill] = useState<Skill | null>(null);
  const [content, setContent] = useState<SkillContent | null>(null);
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);

  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editContent, setEditContent] = useState("");
  const [hasChanges, setHasChanges] = useState(false);
  const hasChangesRef = useRef(false);
  const skillIdRef = useRef(skillId);
  const loadedSkillIdRef = useRef<string | null>(null);

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  // Child skills state
  const [childSkills, setChildSkills] = useState<Skill[]>([]);
  const [allSkills, setAllSkills] = useState<Skill[]>([]);
  const [showAddChildDialog, setShowAddChildDialog] = useState(false);
  const [addingChildId, setAddingChildId] = useState<string>("");
  const [isAddingChild, setIsAddingChild] = useState(false);
  const [removingChildId, setRemovingChildId] = useState<string | null>(null);
  const [childrenError, setChildrenError] = useState<string | null>(null);
  const [allSkillsError, setAllSkillsError] = useState<string | null>(null);
  const [addChildError, setAddChildError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      if (skillIdRef.current !== skillId) {
        skillIdRef.current = skillId;
        hasChangesRef.current = false;
      }
      setLoading(true);
      setLoadError(null);
      setNotFound(false);
      try {
        const {
          skill: skillRes,
          content: contentRes,
          files: filesRes,
          members: membersRes,
          allSkills: allSkillsRes,
        } = await loadSkillDetailAction(skillId);
        if (cancelled) return;

        if (skillRes.error || !skillRes.data) {
          if (isApiNotFound(skillRes)) {
            setNotFound(true);
          } else {
            setLoadError(apiErrorMessage(skillRes, t("error.loadSkill")));
          }
          return;
        }
        if (contentRes.error) {
          setLoadError(apiErrorMessage(contentRes, t("error.loadSkill")));
          return;
        }

        const skillData = skillRes.data as Skill;
        const contentData = contentRes.data as SkillContent;
        loadedSkillIdRef.current = skillId;

        setSkill(skillData);
        setContent(contentData);
        setFiles((filesRes.data as { files: SkillFile[] })?.files || []);
        setFilesError(
          filesRes.error ? apiErrorMessage(filesRes, t("error.loadFiles")) : null
        );
        setChildSkills((membersRes.data as Skill[]) || []);
        setChildrenError(
          membersRes.error
            ? apiErrorMessage(membersRes, tChildren("loadFailed"))
            : null
        );
        setAllSkills((allSkillsRes.data as Skill[]) || []);
        setAllSkillsError(
          allSkillsRes.error
            ? apiErrorMessage(allSkillsRes, tChildren("loadOptionsFailed"))
            : null
        );

        if (!hasChangesRef.current) {
          setEditName(skillData.name);
          setEditDescription(skillData.description || "");
          setEditContent(contentData?.content || "");
        }

        if (contentData?.content) {
          setSelectedFile("SKILL.md");
          setFileContent(contentData.content);
        }
      } catch (err) {
        if (cancelled) return;
        console.error("Failed to load skill", err);
        setLoadError(`${t("error.loadSkill")}: ${formatApiError(err)}`);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void fetchData();
    return () => {
      cancelled = true;
    };
  }, [skillId, reloadKey, t, tChildren]);

  useEffect(() => {
    if (loadedSkillIdRef.current !== skillId || !skill || !content) return;

    const nameChanged = editName !== skill.name;
    const descChanged = editDescription !== (skill.description || "");
    const contentChanged =
      skill.source_type === "content" &&
      editContent !== (content?.content || "");

    const changed = nameChanged || descChanged || contentChanged;
    hasChangesRef.current = changed;
    setHasChanges(changed);
    if (changed) {
      setSaved(false);
      setActionError(null);
    }
  }, [skillId, editName, editDescription, editContent, skill, content]);

  const handleFileSelect = async (path: string) => {
    setSelectedFile(path);
    setLoadingFile(true);
    setIsEditing(false);
    setFileError(null);

    try {
      if (path === "SKILL.md") {
        setFileContent(editContent || content?.content || "");
      } else {
        const result = await getSkillFile(skillId, path);
        if (result.error) {
          setFileError(apiErrorMessage(result, t("error.loadFileContent")));
          setFileContent(null);
        } else {
          const fileData = result.data as { url?: string };
          if (fileData?.url) {
            const response = await fetch(fileData.url);
            if (!response.ok) {
              setFileError(
                `${t("error.loadFileContent")} (${response.status})`
              );
              setFileContent(null);
            } else {
              setFileContent(await response.text());
            }
          } else {
            setFileContent(null);
          }
        }
      }
    } catch (err) {
      console.error("Failed to load skill file", err);
      setFileError(`${t("error.loadFileContent")}: ${formatApiError(err)}`);
      setFileContent(null);
    } finally {
      setLoadingFile(false);
    }
  };

  const handleSave = async () => {
    if (!skill) return;

    setSaving(true);
    setActionError(null);
    try {
      const updateData: SkillUpdateRequest = {
        name: editName,
        description: editDescription || null,
      };

      if (skill.source_type === "content") {
        updateData.content = editContent;
      }

      const result = await updateSkill(skillId, updateData);

      if (result.error) {
        setActionError(apiErrorMessage(result, t("error.saveSkill")));
        return;
      }

      const updatedSkill = result.data as Skill | undefined;
      if (updatedSkill?.id && updatedSkill.id !== skillId) {
        router.replace(`/skills/${updatedSkill.id}`);
        router.refresh();
        return;
      }

      const [skillRes, contentRes] = await Promise.all([
        getSkill(skillId),
        getSkillContent(skillId),
      ]);

      if (skillRes.error || contentRes.error) {
        setActionError(
          apiErrorMessage(
            skillRes.error ? skillRes : contentRes,
            t("error.reloadAfterSave")
          )
        );
      }
      if (skillRes.data) {
        setSkill(skillRes.data as Skill);
      }
      if (contentRes.data) {
        setContent(contentRes.data as SkillContent);
      }

      setHasChanges(false);
      hasChangesRef.current = false;
      setIsEditing(false);
      setSaved(true);
    } catch (err) {
      console.error("Failed to save skill", err);
      setActionError(`${t("error.saveSkill")}: ${formatApiError(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const handleInstallCatalogSkill = async () => {
    if (!skill) return;

    setInstalling(true);
    setActionError(null);
    try {
      const result = await installSkill(skillId);
      const installed = result.data as Skill | undefined;

      if (result.error || !installed?.id) {
        setActionError(apiErrorMessage(result, t("error.installSkill")));
        return;
      }

      router.replace(`/skills/${installed.id}`);
      router.refresh();
    } catch (err) {
      console.error("Failed to install skill", err);
      setActionError(`${t("error.installSkill")}: ${formatApiError(err)}`);
    } finally {
      setInstalling(false);
    }
  };

  const handleAddChildSkill = async () => {
    if (!addingChildId) return;
    setIsAddingChild(true);
    setAddChildError(null);
    try {
      const result = await addSkillMember(skillId, addingChildId);
      if (result.error) {
        setAddChildError(apiErrorMessage(result, tChildren("addFailed")));
        return;
      }
      setShowAddChildDialog(false);
      setAddingChildId("");
      const membersRes = await listSkillMembers(skillId);
      if (membersRes.error) {
        setChildrenError(apiErrorMessage(membersRes, tChildren("loadFailed")));
        return;
      }
      setChildrenError(null);
      setChildSkills((membersRes.data as Skill[]) || []);
    } catch (err) {
      console.error("Failed to add child skill", err);
      setAddChildError(`${tChildren("addFailed")}: ${formatApiError(err)}`);
    } finally {
      setIsAddingChild(false);
    }
  };

  const handleRemoveChildSkill = async (childId: string) => {
    setRemovingChildId(childId);
    setChildrenError(null);
    try {
      const result = await removeSkillMember(skillId, childId);
      if (result.error) {
        setChildrenError(apiErrorMessage(result, tChildren("removeFailed")));
        return;
      }
      setChildSkills((prev) => prev.filter((s) => s.id !== childId));
    } catch (err) {
      console.error("Failed to remove child skill", err);
      setChildrenError(`${tChildren("removeFailed")}: ${formatApiError(err)}`);
    } finally {
      setRemovingChildId(null);
    }
  };

  if (loading) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("title"), href: "/skills" },
            { label: skillId },
          ],
        }}
      >
        <DetailSkeleton />
      </ContentBlock>
    );
  }

  if (loadError || !skill) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("title"), href: "/skills" },
            { label: skillId },
          ],
        }}
      >
        <div className="flex h-64 items-center justify-center">
          {notFound || !loadError ? (
            <EmptyState
              title={t("error.skillNotFound")}
              description=""
              icons={[FileX]}
              action={{
                label: t("backToSkills"),
                onClick: () => router.push("/skills"),
              }}
            />
          ) : (
            <EmptyState
              title={t("error.loadSkill")}
              description={loadError}
              icons={[FileX]}
              action={{
                label: tCommon("retry"),
                onClick: () => setReloadKey((key) => key + 1),
              }}
              additionAction={{
                label: t("backToSkills"),
                onClick: () => router.push("/skills"),
              }}
            />
          )}
        </div>
      </ContentBlock>
    );
  }

  const isCatalog = Boolean(skill.is_catalog);
  const isContentEditable = skill.source_type === "content";
  const canEditFile =
    !isCatalog && isContentEditable && selectedFile === "SKILL.md";
  const editModeTab = isEditing ? "edit" : "view";

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
            {isCatalog ? (
              <Button
                size="xs"
                onClick={handleInstallCatalogSkill}
                disabled={installing}
              >
                {installing ? (
                  <Loader2 className="mr-2 animate-spin" />
                ) : (
                  <Plus className="mr-2" />
                )}
                {installing ? tDetail("installing") : tDetail("customize")}
              </Button>
            ) : (
              <>
                {saved && !hasChanges && (
                  <span className="text-xs text-muted-foreground">
                    {tCommon("saved")}
                  </span>
                )}
                <Button
                  variant="outline"
                  size="xs"
                  onClick={handleSave}
                  disabled={!hasChanges || saving}
                >
                  {saving ? (
                    <Loader2 className="mr-2 animate-spin" />
                  ) : (
                    <Save className="mr-2" />
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
                  description={t("confirm.deleteSkill", {
                    skillName: skill.name,
                  })}
                />
              </>
            )}
          </div>
        ),
      }}
    >
      <div className="flex h-full w-full overflow-hidden">
        {/* Main Content Area */}
        <div className="flex-1 overflow-auto p-4 md:p-6">
          <div className="h-full max-w-4xl mx-auto flex flex-col gap-3">
            {actionError && <FormError>{actionError}</FormError>}
            {filesError && <FormError>{filesError}</FormError>}
            <Card className="h-full flex flex-col overflow-hidden p-0 cursor-default hover:shadow-none">
              <CardHeader className="border-b border-border/70 bg-sidebar p-3 flex flex-row items-center justify-between shrink-0 space-y-0">
                <CardTitle className="text-xs font-mono">
                  {selectedFile || tDetail("selectFile")}
                </CardTitle>
                <div className="flex items-center gap-2">
                  {hasChanges && !isCatalog && (
                    <Button
                      variant="outline"
                      size="xs"
                      className="border-border/70 bg-background/60 shadow-none hover:bg-muted/70"
                      onClick={handleSave}
                      disabled={saving}
                    >
                      {saving ? (
                        <Loader2 className="mr-2 animate-spin" />
                      ) : (
                        <Save className="mr-2" />
                      )}
                      {tDetail("save")}
                    </Button>
                  )}

                  {isCatalog && (
                    <Button
                      size="xs"
                      className="border-border/70 bg-background/60 shadow-none hover:bg-muted/70"
                      variant="outline"
                      onClick={handleInstallCatalogSkill}
                      disabled={installing}
                    >
                      {installing ? (
                        <Loader2 className="mr-2 animate-spin" />
                      ) : (
                        <Plus className="mr-2" />
                      )}
                      {installing
                        ? tDetail("installing")
                        : tDetail("customize")}
                    </Button>
                  )}

                  {canEditFile && (
                    <AnimatedTabs
                      layoutId="skill-edit-toggle"
                      tabs={[
                        {
                          value: "view",
                          label: tDetail("view"),
                          icon: <Eye className="h-3.5 w-3.5" />,
                        },
                        {
                          value: "edit",
                          label: tDetail("edit"),
                          icon: <Pencil className="h-3.5 w-3.5" />,
                        },
                      ]}
                      activeTab={editModeTab}
                      onChange={(val) => setIsEditing(val === "edit")}
                      className="w-auto rounded-md border border-border/70 bg-background/60 p-0.5 text-xs font-normal"
                      tabClassName="flex-none px-2 py-1 gap-1"
                      labelClassName="sr-only"
                      activeIndicatorClassName="bg-background shadow-none ring-1 ring-border/70"
                      hoverIndicatorClassName="bg-muted/60"
                    />
                  )}
                </div>
              </CardHeader>
              <CardContent className="p-0 flex-1 overflow-auto relative">
                {loadingFile ? (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <LoadingSpinner />
                  </div>
                ) : fileError ? (
                  <div className="p-4">
                    <FormError>{fileError}</FormError>
                  </div>
                ) : !selectedFile ? (
                  <div className="absolute inset-0 flex items-center justify-center p-6">
                    <EmptyState
                      className="max-w-none w-full border border-border/70 p-8 hover:bg-muted/30"
                      title={tDetail("selectFile")}
                      description=""
                      icons={[FileText]}
                    />
                  </div>
                ) : !fileContent ? (
                  <div className="absolute inset-0 flex items-center justify-center p-6">
                    <EmptyState
                      className="max-w-none w-full border border-border/70 p-8 hover:bg-muted/30"
                      title={tDetail("emptyFile")}
                      description=""
                      icons={[FileX]}
                    />
                  </div>
                ) : isEditing && canEditFile ? (
                  <textarea
                    value={editContent}
                    onChange={(e) => {
                      hasChangesRef.current = true;
                      setEditContent(e.target.value);
                    }}
                    className="w-full h-full p-4 bg-background text-sm font-mono leading-relaxed resize-none focus:outline-none"
                    spellCheck={false}
                  />
                ) : (
                  <div className="p-4 space-y-4">
                    {hasFrontmatter && (
                      <Section
                        title={tDetail("skillConfiguration")}
                        className="shadow-none"
                        contentClassName="p-4"
                      >
                        <pre className="text-xs font-mono whitespace-pre-wrap text-foreground">
                          {parsed?.rawFrontmatter}
                        </pre>
                      </Section>
                    )}

                    <div className="prose prose-sm dark:prose-invert max-w-none pb-10 prose-headings:font-semibold prose-headings:tracking-tight prose-h1:text-xl prose-h1:mt-6 prose-h1:mb-2 prose-h2:text-lg prose-h2:mt-5 prose-h2:mb-2 prose-h3:text-base prose-h3:mt-4 prose-h3:mb-1.5 prose-p:leading-relaxed prose-ul:my-3 prose-ol:my-3 prose-li:my-1 prose-pre:bg-muted prose-pre:border prose-pre:border-border/70 prose-pre:rounded-md prose-pre:p-4 prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
                      <Streamdown>{parsed?.body || fileContent}</Streamdown>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
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
      {!isCatalog && (
        <div className="border-t px-6 py-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">
              {tChildren("title", { count: childSkills.length })}
            </h3>
            <Button
              size="xs"
              variant="outline"
              onClick={() => {
                setAddChildError(null);
                setShowAddChildDialog(true);
              }}
            >
              <Plus className="mr-1.5" />
              {tChildren("add")}
            </Button>
          </div>
          {childrenError && <FormError>{childrenError}</FormError>}
          {childSkills.length === 0 ? (
            !childrenError && (
              <p className="text-sm text-muted-foreground">
                {tChildren("empty")}
              </p>
            )
          ) : (
            <ul className="space-y-1">
              {childSkills.map((child) => (
                <li
                  key={child.id}
                  className="flex items-center justify-between rounded border px-3 py-2 text-sm"
                >
                  <span>{child.name}</span>
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => handleRemoveChildSkill(child.id)}
                    disabled={removingChildId === child.id}
                  >
                    {removingChildId === child.id ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Trash2 className="text-destructive" />
                    )}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Add Child Skill Dialog */}
      <Dialog open={showAddChildDialog} onOpenChange={setShowAddChildDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{tChildren("add")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {allSkillsError && <FormError>{allSkillsError}</FormError>}
            {addChildError && <FormError>{addChildError}</FormError>}
            <select
              className="w-full rounded border bg-background px-3 py-2 text-sm"
              value={addingChildId}
              onChange={(e) => {
                setAddingChildId(e.target.value);
                setAddChildError(null);
              }}
            >
              <option value="">{tChildren("selectPlaceholder")}</option>
              {allSkills
                .filter(
                  (s) =>
                    s.id !== skillId &&
                    !childSkills.some((c) => c.id === s.id)
                )
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </select>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowAddChildDialog(false)}
            >
              {tCommon("cancel")}
            </Button>
            <Button
              onClick={handleAddChildSkill}
              disabled={!addingChildId || isAddingChild}
            >
              {isAddingChild ? (
                <Loader2 className="mr-2 animate-spin" />
              ) : null}
              {tCommon("add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
