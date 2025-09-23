import React, { useState } from 'react';
import { Download } from 'lucide-react';
import { Button } from './button';
import { getFileTypeInfo, formatFileSize, isImageFile } from '@/utils/fileUtils';

interface FileCardMessageProps {
  file: File;
  onDownload: () => void;
  className?: string;
}

export const FileCardMessage: React.FC<FileCardMessageProps> = ({ file, onDownload, className = '' }) => {
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [imageLoading, setImageLoading] = useState(false);
  const fileInfo = getFileTypeInfo(file);
  const IconComponent = fileInfo.icon;
  const isImage = isImageFile(file);

  // Create image preview when component mounts
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
      <div className={`inline-block relative ${className}`}>
        <div className={`flex-shrink-0 border w-10 h-10 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center relative`}>
          {imageLoading ? (
            <div className="w-6 h-6 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
          ) : imagePreview && !imageError ? (
            <img
              src={imagePreview}
              alt={file.name}
              className="w-full h-full object-cover rounded-lg"
              onError={() => setImageError(true)}
            />
          ) : (
            <IconComponent className={`h-6 w-6 ${fileInfo.color}`} />
          )}

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onDownload}
            className="h-5 w-5 p-0 bg-zinc-300 dark:bg-zinc-700 text-white hover:bg-zinc-900 dark:hover:bg-gray-600 rounded-full flex-shrink-0 absolute -top-1 -right-1"
          >
            <Download className="h-3 w-3" />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative inline-flex items-center gap-2 bg-white dark:bg-zinc-900 rounded-lg pl-1 pr-4 py-1 border relative ${className}`}>
      {/* File Icon */}
      <div className={`flex-shrink-0 w-8 h-8 rounded-lg bg-gray-100 dark:bg-gray-700 flex items-center justify-center overflow-hidden`}>
        <IconComponent className={`h-5 w-5 text-gray-500`} />
      </div>
      
      {/* File Info */}
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-gray-900 dark:text-gray-100 truncate">
          {file.name}
        </div>
        <div className="text-xs text-gray-500 dark:text-gray-400">
          {fileInfo.type}
        </div>
      </div>
      
      {/* Download Button */}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onDownload}
        className="h-5 w-5 p-0 bg-zinc-300 dark:bg-zinc-700 text-white hover:bg-zinc-900 dark:hover:bg-gray-600 rounded-full flex-shrink-0  absolute -top-1 -right-1"
      >
        <Download className="h-3 w-3" />
      </Button>
    </div>
  );
};

export default FileCardMessage;
