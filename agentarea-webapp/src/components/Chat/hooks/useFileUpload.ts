/**
 * Hook for managing file upload functionality
 * Handles file selection, removal, and state management
 */

import { useRef, useState } from "react";

export interface UseFileUploadReturn {
  /**
   * Array of currently selected files
   */
  selectedFiles: File[];

  /**
   * Ref for the hidden file input element
   */
  fileInputRef: React.RefObject<HTMLInputElement>;

  /**
   * Handle file selection from input
   */
  handleFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;

  /**
   * Remove a file by index
   */
  removeFile: (index: number) => void;

  /**
   * Programmatically open the file dialog
   */
  openFileDialog: () => void;

  /**
   * Clear all selected files
   */
  clearFiles: () => void;
}

/**
 * Custom hook for managing file uploads in chat
 *
 * Features:
 * - File selection via input element
 * - Multiple file support
 * - Remove individual files
 * - Programmatic file dialog trigger
 * - Clear all files
 *
 * @example
 * ```typescript
 * const {
 *   selectedFiles,
 *   fileInputRef,
 *   handleFileSelect,
 *   removeFile,
 *   openFileDialog,
 *   clearFiles
 * } = useFileUpload();
 *
 * return (
 *   <>
 *     <input
 *       ref={fileInputRef}
 *       type="file"
 *       multiple
 *       onChange={handleFileSelect}
 *       className="hidden"
 *     />
 *     <button onClick={openFileDialog}>Attach Files</button>
 *     {selectedFiles.map((file, i) => (
 *       <FileCard key={i} file={file} onRemove={() => removeFile(i)} />
 *     ))}
 *   </>
 * );
 * ```
 */
export function useFileUpload(): UseFileUploadReturn {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /**
   * Handle file selection from input element
   * Adds new files to existing selection
   */
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setSelectedFiles((prev) => [...prev, ...files]);
  };

  /**
   * Remove a file from selection by index
   */
  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  /**
   * Programmatically trigger the file input dialog
   */
  const openFileDialog = () => {
    fileInputRef.current?.click();
  };

  /**
   * Clear all selected files
   */
  const clearFiles = () => {
    setSelectedFiles([]);
    // Also reset the file input element
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return {
    selectedFiles,
    fileInputRef,
    handleFileSelect,
    removeFile,
    openFileDialog,
    clearFiles,
  };
}
