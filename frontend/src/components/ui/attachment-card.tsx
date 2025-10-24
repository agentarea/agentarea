import React, { useState } from "react";
import { Download, X } from "lucide-react";
import { getFileTypeInfo, isImageFile } from "@/utils/fileUtils";
import { Button } from "./button";

interface AttachmentCardProps {
  file: File;
  onAction: () => void;
  actionType: "remove" | "download";
  className?: string;
}

export const AttachmentCard: React.FC<AttachmentCardProps> = ({
  file,
  onAction,
  actionType,
  className = "",
}) => {
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [imageLoading, setImageLoading] = useState(false);
  const fileInfo = getFileTypeInfo(file);
  const IconComponent = fileInfo.icon;
  const isImage = isImageFile(file);

  // Prepare action button visuals
  const actionSizeClass = actionType === "remove" ? "h-4 w-4" : "h-5 w-5";

  React.useEffect(() => {
    if (isImage && !imageError) {
      setImageLoading(true);
      const reader = new FileReader();
      reader.onload = (e) => {
        setImagePreview(e.target?.result as string);
        setImageLoading(false);
      };
      reader.onerror = () => {
        setImageError(true);
        setImageLoading(false);
      };
      reader.readAsDataURL(file);
    }
  }, [file, isImage, imageError]);

  if (isImage) {
    return (
      <div className={`relative inline-block ${className}`}>
        <div
          className={`relative flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-lg border bg-gray-100 dark:bg-gray-700`}
        >
          {imageLoading ? (
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" />
          ) : imagePreview && !imageError ? (
            <img
              src={imagePreview}
              alt={file.name}
              className="h-full w-full rounded-lg object-cover"
              onError={() => setImageError(true)}
            />
          ) : (
            <IconComponent className={`h-5 w-5 ${fileInfo.color}`} />
          )}

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onAction}
            className={`${actionSizeClass} absolute -right-1 -top-1 flex-shrink-0 rounded-full bg-zinc-700 p-0 text-white hover:bg-zinc-900 dark:hover:bg-gray-600`}
          >
            {actionType === "remove" ? (
              <X className="h-3 w-3" />
            ) : (
              <Download className="h-3 w-3" />
            )}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`relative inline-flex h-12 items-center gap-2 rounded-lg border bg-white pl-1 pr-4 dark:bg-zinc-900 ${className}`}
    >
      <div
        className={`flex h-9 w-9 flex-shrink-0 items-center justify-center overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-700`}
      >
        <IconComponent className={`h-5 w-5 text-gray-500`} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="max-w-[160px] truncate text-xs font-medium text-gray-900 dark:text-gray-100">
          {file.name}
        </div>
        <div className="text-xs text-gray-500 dark:text-gray-400">
          {fileInfo.type}
        </div>
      </div>

      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onAction}
        className={`${actionSizeClass} absolute -right-1 -top-1 flex-shrink-0 rounded-full bg-zinc-700 p-0 text-white hover:bg-zinc-900 dark:hover:bg-gray-600`}
      >
        {actionType === "remove" ? (
          <X className="h-3 w-3" />
        ) : (
          <Download className="h-3 w-3" />
        )}
      </Button>
    </div>
  );
};

export default AttachmentCard;
