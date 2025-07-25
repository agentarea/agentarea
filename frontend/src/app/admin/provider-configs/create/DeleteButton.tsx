'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { deleteProviderConfig } from '@/lib/api';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Trash2 } from 'lucide-react';
import { toast } from 'sonner';

interface DeleteButtonProps {
  configId?: string;
  configName?: string;
}

export default function DeleteButton({ configId, configName }: DeleteButtonProps) {
  const router = useRouter();
  const [isDeleting, setIsDeleting] = useState(false);
  const [isOpen, setIsOpen] = useState(false);

  const handleDelete = async () => {
    if (!configId) {
      console.error('No config ID provided for deletion');
      toast.error('No configuration ID provided for deletion');
      return;
    }

    setIsDeleting(true);
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
      setIsDeleting(false);
      setIsOpen(false);
    }
  };


  

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="destructive" size="sm">
          <Trash2 className="h-4 w-4" />
          Delete Configuration
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-[400px] overflow-hidden">
        <DialogHeader>
          <DialogTitle className="pb-2">Delete Provider Configuration</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete <span className="font-bold">{configName ? `"${configName}"` : 'this provider configuration'}</span>? 
            This action cannot be undone and will permanently remove the configuration.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button 
            variant="outline" 
            size="sm"
            onClick={() => setIsOpen(false)} 
            disabled={isDeleting}
          >
            Cancel
          </Button>
          <Button 
            size="sm"
            onClick={handleDelete} 
            disabled={isDeleting}
            variant="destructive"
          >
            {isDeleting ? 'Deleting...' : 'Delete'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
} 