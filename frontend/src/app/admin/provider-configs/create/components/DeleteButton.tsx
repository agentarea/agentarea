'use client';

import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { deleteProviderConfig } from '@/lib/api';
import { Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import BaseModal from '@/components/BaseModal';

interface DeleteButtonProps {
  configId?: string;
  configName?: string;
}

export default function DeleteButton({ configId, configName }: DeleteButtonProps) {
  const router = useRouter();

  const handleDelete = async () => {
    if (!configId) {
      console.error('No config ID provided for deletion');
      toast.error('No configuration ID provided for deletion');
      return;
    }

    try {
      const { error } = await deleteProviderConfig(configId);
      
      if (error) {
        console.error('Failed to delete provider config:', error);
        const errorMessage = error.detail?.[0]?.msg || 'Unknown error';
        toast.error(`Failed to delete configuration: ${errorMessage}`);
        return;
      }

      // Success - redirect to the provider configs list
      toast.success('Configuration deleted successfully');
      router.push('/admin/provider-configs');
      router.refresh();
    } catch (err) {
      console.error('Error deleting provider config:', err);
      toast.error('An unexpected error occurred while deleting the configuration');
    } finally {
    }
  };

  return (
    <BaseModal
      title="Delete Provider Configuration"
      description={`Are you sure you want to delete ${configName ? `"${configName}"` : 'this provider configuration'}? This action cannot be undone and will permanently remove the configuration.`}
      onConfirm={handleDelete}
      type="delete"
    >
      <Button variant="destructiveOutline" size="sm">
        <Trash2 className="h-4 w-4" />
        Delete
      </Button>
    </BaseModal>
  );
} 