import { useTranslations } from 'next-intl';
import { User, Globe } from 'lucide-react';
import SettingsCard from './components/SettingsCard';
import { ThemeToggle } from "@/components/ui/theme-toggle";
import LanguageSelect from './components/LanguageSelect';
import ProfileForm from './components/ProfileForm';
import RowControl from './components/RowControl';

export default function SettingsPage() {
    const t = useTranslations('SettingsPage');

    // TODO: get user from backend
    const user = {
        name: 'John Doe',
        email: 'john.doe@example.com',
        avatar: 'https://github.com/shadcn.png'
    }

    return (
        <div className="content">
            <div className="flex items-center gap-4 mb-8">
                <h1>{t('title')}</h1>
            </div>

            <div className="mx-auto space-y-5 max-w-4xl">
                {/* Profile Section */}
                <SettingsCard
                    title={t('profile.title')}
                    description={t('profile.description')}
                    icon={User}
                >
                    <ProfileForm {...user} />
                </SettingsCard>

                {/* Preferences Section */}
                <SettingsCard
                    title={t('preferences.title')}
                    description={t('preferences.description')}
                    icon={Globe}
                >
                    <>
                        {/* LANGUAGE SECTION */}
                        <RowControl title={t('preferences.language')} description={t('preferences.languageDescription')}>
                            <LanguageSelect />
                        </RowControl>

                        {/* THEME SECTION */}
                        <RowControl title={t('preferences.theme')} description={t('preferences.themeDescription')}>
                            <ThemeToggle />
                        </RowControl>
                    </>
                </SettingsCard>

                {/* Subscription Section */}
                {/* <SettingsCard
                    title={t('subscription.title')}
                    description={t('subscription.description')}
                    icon={CreditCard}
                >
                    <>
                        <div className="flex items-center justify-between p-4 rounded-lg bg-primary/5 dark:bg-zinc-700/50">
                            <div className="space-y-0.5">
                                <Label className="text-base text-primary dark:text-zinc-200">Current Plan</Label>
                                <p className="text-sm text-muted-foreground">Manage your subscription</p>
                            </div>
                            <Badge variant="default" className="px-4 py-1.5 text-base bg-primary/90">Premium</Badge>
                        </div>
                        <div className="grid gap-4 p-4 rounded-lg bg-primary/5 dark:bg-zinc-700/50">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <Calendar className="w-4 h-4 text-primary/60 dark:text-zinc-400" />
                                    <span className="text-sm">Next Billing Date</span>
                                </div>
                                <span className="text-sm font-medium">January 1, 2024</span>
                            </div>
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <CreditCard className="w-4 h-4 text-primary/60 dark:text-zinc-400" />
                                    <span className="text-sm">Payment Method</span>
                                </div>
                                <span className="text-sm font-medium">•••• 4242</span>
                            </div>
                        </div>
                        <div className="flex justify-end gap-4">
                            <Button variant="outline" className="gap-2 hover:bg-primary/5">
                                <CreditCard className="w-4 h-4" />
                                Change Plan
                            </Button>
                            <Button variant="outline" className="gap-2 hover:bg-primary/5">
                                <CreditCard className="w-4 h-4" />
                                Update Payment
                            </Button>
                        </div>
                    </>
                </SettingsCard> */}
            </div>
        </div>
    )
}   