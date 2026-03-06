"use client";

import { useTranslations } from "next-intl";
import { File } from "lucide-react";
import { SkillFile } from "@/lib/browser-api";
import Section from "@/components/TaskInfoPanel/components/Section";
import { FileTree, FileTreeFile, FileTreeFolder } from "@/components/ai-elements/file-tree";

interface SkillFilesProps {
  files: SkillFile[];
  onFileSelect?: (path: string) => void;
  selectedFile?: string | null;
}

export default function SkillFiles({ files, onFileSelect, selectedFile }: SkillFilesProps) {
  const tDetail = useTranslations("SkillsPage.detail");

  const buildFileTree = (files: SkillFile[]): FileNode[] => {
    const root: FileNode[] = [];
    const nodeMap = new Map<string, FileNode>();

    const sortedFiles = [...files].sort((a, b) => a.path.localeCompare(b.path));

    for (const file of sortedFiles) {
      const parts = file.path.split("/");
      let currentPath = "";
      let currentLevel = root;

      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const isLast = i === parts.length - 1;
        currentPath = currentPath ? `${currentPath}/${part}` : part;

        let node = nodeMap.get(currentPath);

        if (!node) {
          node = {
            name: part,
            path: currentPath,
            type: isLast ? "file" : "folder",
            children: [],
            ...(isLast && { size: file.size }),
          };
          nodeMap.set(currentPath, node);
          currentLevel.push(node);
        }

        if (!isLast) {
          currentLevel = node.children;
        }
      }
    }

    const sortNodes = (nodes: FileNode[]) => {
      nodes.sort((a, b) => {
        if (a.type === b.type) {
          return a.name.localeCompare(b.name);
        }
        return a.type === "folder" ? -1 : 1;
      });
      nodes.forEach((node) => {
        if (node.children.length > 0) {
          sortNodes(node.children);
        }
      });
    };

    sortNodes(root);
    return root;
  };

  const renderFileTree = (nodes: FileNode[]): React.ReactNode => {
    return nodes.map((node) => {
      if (node.type === "folder") {
        return (
          <FileTreeFolder key={node.path} name={node.name} path={node.path}>
            {renderFileTree(node.children)}
          </FileTreeFolder>
        );
      }
      return (
        <FileTreeFile key={node.path} name={node.name} path={node.path}>
          <span className="size-4" />
          <File className="size-4 text-muted-foreground shrink-0" />
          <span className="truncate flex-1">{node.name}</span>
          {node.size !== undefined && (
            <span className="text-xs text-muted-foreground ml-2">
              {(node.size / 1024).toFixed(1)} KB
            </span>
          )}
        </FileTreeFile>
      );
    });
  };

  const fileTreeNodes = buildFileTree(files);

  return (
    <Section title={tDetail("files")} contentClassName="space-y-3 text-xs">
      {fileTreeNodes.length > 0 ? (
        <FileTree
          defaultExpanded={new Set()}
          selectedPath={selectedFile || undefined}
          onSelect={(path) => onFileSelect?.(path)}
        >
          {renderFileTree(fileTreeNodes)}
        </FileTree>
      ) : (
        <div className="text-muted-foreground text-center py-4">
          {tDetail("emptyFile")}
        </div>
      )}
    </Section>
  );
}

interface FileNode {
  name: string;
  path: string;
  type: "file" | "folder";
  children: FileNode[];
  size?: number;
}
