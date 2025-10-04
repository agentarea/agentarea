import { useTranslations } from 'next-intl';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { ExternalLink, Shield, Mail, User as UserIcon } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';

export default function ProfileForm(defaultValues: { name: string, email: string, avatar: string }) {
    const t = useTranslations('SettingsPage');

    const handleManageAccount = () => {
        // This would typically open the authentication provider's user profile management
        // For Ory, this could be a custom profile page or Ory Account Experience
        alert('Profile management through authentication provider not yet implemented');
    };

    return (
        <div className="space-y-8">
            {/* Profile Overview */}
            <div className="flex flex-col sm:flex-row items-start gap-6">
                <div className="relative shrink-0">
                    <Avatar className="h-20 w-20 border-2 border-gray-200 dark:border-gray-600">
                        <AvatarImage src={defaultValues.avatar} />
                        <AvatarFallback className="text-xl bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">
                            {defaultValues.name.split(' ').map((n: string) => n[0]).join('')}
                        </AvatarFallback>
                    </Avatar>
                    <Badge variant="secondary" className="absolute -bottom-1 -right-1 text-xs bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-400 border-0">
                        <Shield className="w-3 h-3 mr-1" />
                        Verified
                    </Badge>
                </div>
                <div className="flex-1 min-w-0">
                    <h3 className="text-xl font-semibold text-gray-900 dark:text-white truncate">
                        {defaultValues.name}
                    </h3>
                    <div className="flex items-center gap-2 text-gray-600 dark:text-gray-400 mt-1">
                        <Mail className="w-4 h-4 shrink-0" />
                        <span className="text-sm truncate">{defaultValues.email}</span>
                    </div>
                    <p className="text-xs text-gray-500 dark:text-gray-500 mt-3 bg-gray-50 dark:bg-gray-800/50 px-3 py-2 rounded-lg">
                        Account information is managed by your authentication provider and cannot be edited here.
                    </p>
                </div>
            </div>

            {/* Account Details */}
            <div className="space-y-6">
                <div className="grid gap-6 md:grid-cols-2">
                    <div className="space-y-2">
                        <Label className="text-sm font-medium text-gray-700 dark:text-gray-300">Display Name</Label>
                        <div className="relative">
                            <Input 
                                value={defaultValues.name} 
                                disabled 
                                className="bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 border-gray-200 dark:border-gray-700 cursor-not-allowed" 
                            />
                            <div className="absolute inset-y-0 right-0 flex items-center pr-3">
                                <Shield className="w-4 h-4 text-gray-400" />
                            </div>
                        </div>
                    </div>
                    <div className="space-y-2">
                        <Label className="text-sm font-medium text-gray-700 dark:text-gray-300">Email Address</Label>
                        <div className="relative">
                            <Input 
                                value={defaultValues.email} 
                                disabled 
                                className="bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 border-gray-200 dark:border-gray-700 cursor-not-allowed" 
                            />
                            <div className="absolute inset-y-0 right-0 flex items-center pr-3">
                                <Shield className="w-4 h-4 text-gray-400" />
                            </div>
                        </div>
                    </div>
                </div>

                {/* Action Section */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pt-6 border-t border-gray-200 dark:border-gray-700">
                    <div className="flex-1">
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                            Need to update your profile information?
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">
                            Use your authentication provider&#39;s profile management to make changes.
                        </p>
                    </div>
                    <Button onClick={handleManageAccount} variant="outline" className="shrink-0 gap-2">
                        <ExternalLink className="w-4 h-4" />
                        Manage Account
                    </Button>
                </div>
            </div>
        </div>
    )
}