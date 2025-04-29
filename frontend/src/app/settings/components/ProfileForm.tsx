import { useTranslations } from 'next-intl';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { User, Camera } from 'lucide-react';
import { Label } from '@/components/ui/label';

// TODO: add avatar upload, add save button, add form component
export default function ProfileForm(defaultValues: { name: string, email: string, avatar: string }) {
    const t = useTranslations('SettingsPage');

    return (
        <div className="flex flex-col sm:flex-row items-center sm:space-x-8">
            <div className="relative">
                <Avatar className="h-28 w-28 border-4 border-primary/30 shadow-lg">
                    <AvatarImage src={defaultValues.avatar} />
                    <AvatarFallback className="text-3xl">{defaultValues.name.split(' ').map((n: string) => n[0]).join('')}</AvatarFallback>
                </Avatar>
                <Button size="icon" className="absolute bottom-2 right-2 bg-white/80 dark:bg-zinc-800/80 border border-primary/30 shadow-md p-2 rounded-full hover:bg-primary/10 transition-all">
                    <Camera className="w-5 h-5 text-primary" />
                </Button>
            </div>
            <div className="space-y-4 flex-1">
                <div className="grid gap-6 md:grid-cols-2">
                    <div className="space-y-2">
                        <Label htmlFor="name" className="text-primary/80 dark:text-zinc-200 font-medium">{t('profile.name')}</Label>
                        <Input id="name" defaultValue={defaultValues.name} className="dark:bg-zinc-900" placeholder="Enter your full name" />
                    </div>
                    <div className="space-y-2">
                        <Label htmlFor="email" className="text-primary/80 dark:text-zinc-200 font-medium">{t('profile.email')}</Label>
                        <Input id="email" type="email" defaultValue={defaultValues.email} className="dark:bg-zinc-900" placeholder="Enter your email address" />
                    </div>
                </div>
                <div className="flex justify-end mt-2">
                    <Button disabled>
                        <User className="w-4 h-4" />
                        {t('profile.save')}
                    </Button>
                </div>
            </div>
        </div>
    )
}