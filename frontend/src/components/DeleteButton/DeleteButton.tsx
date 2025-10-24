"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import BaseModal from "@/components/BaseModal/BaseModal";
import { Button } from "@/components/ui/button";

interface DeleteButtonProps {
  itemId: string;
  itemName: string;
  onDelete: (itemId: string) => Promise<{ error?: any }>;
  onSuccess?: () => void;
  redirectPath?: string;
  title?: string;
  description?: string;
  errorMessages?: {
    noIdProvided?: string;
    failedToDelete?: string;
    unexpectedError?: string;
  };
  successMessage?: string;
}

export default function DeleteButton({
  itemId,
  itemName,
  onDelete,
  onSuccess,
  redirectPath,
  title = "Delete Item",
  description,
  errorMessages = {},
  successMessage = "Item deleted successfully",
}: DeleteButtonProps) {
  const router = useRouter();
  const tCommon = useTranslations("Common");

  const defaultErrorMessages = {
    noIdProvided: "No ID provided for deletion",
    failedToDelete: "Failed to delete item",
    unexpectedError: "Unexpected error while deleting",
    ...errorMessages,
  };

  const defaultDescription =
    description || tCommon("deleteDescription", { itemName });

  const handleDelete = async () => {
    if (!itemId) {
      console.error("No ID provided for deletion");
      toast.error(defaultErrorMessages.noIdProvided);
      return;
    }

    try {
      const { error } = await onDelete(itemId);

      if (error) {
        console.error("Failed to delete item:", error);
        const errorMessage = error.detail?.[0]?.msg || "Unknown error";
        toast.error(`${defaultErrorMessages.failedToDelete}: ${errorMessage}`);
        return;
      }

      // Success
      toast.success(successMessage);

      if (onSuccess) {
        onSuccess();
      } else if (redirectPath) {
        router.push(redirectPath);
        router.refresh();
      }
    } catch (err) {
      console.error("Error deleting item:", err);
      toast.error(defaultErrorMessages.unexpectedError);
    }
  };

  return (
    <BaseModal
      title={title}
      description={defaultDescription}
      onConfirm={handleDelete}
      type="delete"
    >
      <Button variant="destructiveOutline" size="sm">
        <Trash2 className="h-4 w-4" />
        {tCommon("delete")}
      </Button>
    </BaseModal>
  );
}
