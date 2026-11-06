"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Trash2 } from "lucide-react";
import BaseModal from "@/components/BaseModal/BaseModal";
import { TableRowAction } from "@/components/Table/TableRowAction";
import { Button } from "@/components/ui/button";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  apiErrorMessage,
  formatApiError,
  type ApiResultLike,
} from "@/lib/api-errors";

interface DeleteButtonProps {
  itemId: string;
  itemName: string;
  onDelete: (itemId: string) => Promise<ApiResultLike>;
  onSuccess?: () => void;
  redirectPath?: string;
  title?: string;
  description?: string;
  errorMessages?: {
    noIdProvided?: string;
    failedToDelete?: string;
    unexpectedError?: string;
  };
  size?: "default" | "sm" | "lg" | "icon" | "xs";
  /** As a table row's hover action (TableRowAction), as Secrets deletes. */
  rowAction?: boolean;
}

export default function DeleteButton({
  itemId,
  itemName,
  onDelete,
  onSuccess,
  redirectPath,
  title,
  description,
  errorMessages = {},
  size = "sm",
  rowAction = false,
}: DeleteButtonProps) {
  const router = useWorkspaceRouter();
  const tCommon = useTranslations("Common");
  const [error, setError] = useState<string | null>(null);

  const failedToDelete =
    errorMessages.failedToDelete ?? tCommon("deleteFailed", { itemName });

  const handleDelete = async () => {
    setError(null);
    if (!itemId) {
      console.error("No ID provided for deletion");
      setError(errorMessages.noIdProvided ?? failedToDelete);
      return false;
    }

    try {
      const result = await onDelete(itemId);

      if (result?.error) {
        console.error("Failed to delete item:", result.error);
        setError(apiErrorMessage(result, failedToDelete));
        return false;
      }

      if (onSuccess) {
        onSuccess();
      } else if (redirectPath) {
        router.push(redirectPath);
        router.refresh();
      }
    } catch (err) {
      console.error("Error deleting item:", err);
      setError(
        `${errorMessages.unexpectedError ?? failedToDelete}: ${formatApiError(err)}`
      );
      return false;
    }
  };

  return (
    <BaseModal
      title={title ?? tCommon("delete")}
      description={description || tCommon("deleteDescription", { itemName })}
      error={error}
      onConfirm={handleDelete}
      type="delete"
      onOpenChange={(next) => {
        if (next) setError(null);
      }}
    >
      {rowAction ? (
        <TableRowAction variant="destructiveOutline" icon={<Trash2 />}>
          {tCommon("delete")}
        </TableRowAction>
      ) : (
        <Button variant="destructiveOutline" size={size}>
          <Trash2 />
          {tCommon("delete")}
        </Button>
      )}
    </BaseModal>
  );
}
