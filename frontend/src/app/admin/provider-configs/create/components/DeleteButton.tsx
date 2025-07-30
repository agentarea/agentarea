'use client';

import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { deleteProviderConfig } from '@/lib/api';
import { Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import BaseModal from '@/components/BaseModal';
import { useTranslations } from 'next-intl';

interface DeleteButtonProps {
  configId?: string;
  configName?: string;
}

export default function DeleteButton({ configId, configName }: DeleteButtonProps) {
  const router = useRouter();
  const tCommon = useTranslations("Common");
  const t = useTranslations("Models");
  const tProviderConfigForm = useTranslations("ProviderConfigForm");

  const handleDelete = async () => {
    if (!configId) {
      console.error('No config ID provided for deletion');
      toast.error(t("error.noConfigIdProvided"));
      return;
    }

    try {
      const { error } = await deleteProviderConfig(configId);
      
      if (error) {
        console.error('Failed to delete provider config:', error);
        const errorMessage = error.detail?.[0]?.msg || t("error.unknownError");
        toast.error(`${t("error.failedToDeleteConfiguration")}: ${errorMessage}`);
        return;
      }

      // Success - redirect to the provider configs list
      toast.success(tProviderConfigForm("toast.configurationDeleted"));
      router.push('/admin/provider-configs');
      router.refresh();
    } catch (err) {
      console.error('Error deleting provider config:', err);
      toast.error(t("error.unexpectedErrorWhileDeleting"));
    } finally {
    }
  };

  return (
    <BaseModal
      title={t("deleteProviderConfiguration")}
      description={t("deleteProviderConfigurationDescription", { configName: configName || t("thisProviderConfiguration") })}
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